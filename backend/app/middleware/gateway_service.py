"""
网关服务 (Gateway Service) - 中间层核心
隐藏供应商 API 细节，提供统一的请求处理接口。

架构：
  API 层 (Adapters) → 中间层 (GatewayService) → 供应商层 (Providers)

中间层职责：
  1. 模型解析 - 将模型名称/别名解析为具体的供应商和模型
  2. 供应商路由 - 根据模型自动选择正确的供应商实例
  3. 请求执行 - 调用供应商 API 并返回统一格式的响应
  4. 错误处理 - 统一处理供应商层的错误
"""
from typing import Optional, Generator, Tuple, Callable
from dataclasses import dataclass
import httpx

from app import db
from app.models import Provider, Model
from app.providers import get_provider_class
from app.providers.base import BaseProvider, ProviderConfig
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk
from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse
from app.abstraction.rerank import RerankRequest, RerankResponse


@dataclass
class ResolvedModel:
    """解析后的模型信息"""
    provider_instance: BaseProvider
    db_provider: Provider
    db_model: Model
    real_model_name: str  # 供应商 API 使用的真实模型名称


class GatewayServiceError(Exception):
    """网关服务错误基类"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ModelNotFoundError(GatewayServiceError):
    """模型未找到错误"""
    def __init__(self, model_name: str):
        super().__init__(
            f"Model '{model_name}' not found or not accessible with your API key.",
            status_code=404
        )


class ProviderError(GatewayServiceError):
    """供应商错误"""
    def __init__(self, message: str, status_code: int = 500, error_data: Optional[dict] = None):
        self.error_data = error_data
        super().__init__(message, status_code)


# Internal metadata keys set by the gateway service.
# These are used for internal logic and should NOT be sent to upstream provider APIs.
INTERNAL_METADATA_KEYS = frozenset({'support_thinking', 'support_online_image', 'support_online_video', 'reasoning'})


class GatewayService:
    """
    网关服务 - 中间层核心

    隐藏供应商 API 的细节，API 用户可以使用任何 API 格式
    (/v1/chat/completions, /v1/messages, /v1/responses)
    而不需要关心底层供应商的差异。

    用法:
        service = GatewayService()

        # 非流式请求
        response = service.chat(chat_request, group_id=1)

        # 流式请求
        for chunk in service.stream_chat(chat_request, group_id=1):
            yield chunk.to_sse("openai")
    """

    def resolve_model(self, model_name: str, group_id: Optional[int] = None) -> ResolvedModel:
        """
        解析模型名称/别名，返回供应商实例和模型信息。

        Args:
            model_name: 模型名称或别名
            group_id: 可选的组 ID（用于访问控制）

        Returns:
            ResolvedModel 对象

        Raises:
            ModelNotFoundError: 如果模型未找到或不可访问
        """
        # 先尝试按别名查找，再按名称查找
        # Join with Provider so we can filter by group_id at the DB level,
        # avoiding false misses when the same model name exists in multiple groups.
        query = (
            db.session.query(Model)
            .join(Provider, Model.provider_id == Provider.id)
            .filter((Model.alias == model_name) | (Model.name == model_name))
        )

        if group_id is not None:
            query = query.filter(Provider.group_id == group_id)

        db_model = query.first()

        if not db_model:
            raise ModelNotFoundError(model_name)

        # Reject retired models
        if db_model.is_retired:
            raise GatewayServiceError(
                f"Model '{model_name}' was retired on {db_model.retirement_time.strftime('%Y-%m-%d')} "
                f"and can no longer be used.",
                status_code=410  # 410 Gone
            )

        db_provider = db.session.query(Provider).filter(
            Provider.id == db_model.provider_id
        ).first()

        if not db_provider:
            raise ModelNotFoundError(model_name)

        # 创建供应商实例
        provider_instance = self._create_provider_instance(db_provider)
        if not provider_instance:
            raise GatewayServiceError(
                f"Failed to create provider instance for '{db_provider.name}'",
                status_code=500
            )

        return ResolvedModel(
            provider_instance=provider_instance,
            db_provider=db_provider,
            db_model=db_model,
            real_model_name=db_model.name
        )

    def chat_ex(
        self, request: ChatRequest, group_id: Optional[int] = None
    ) -> Tuple[ChatResponse, ResolvedModel]:
        """
        Same as chat() but also returns the ResolvedModel so callers can
        record usage with the exact provider/model metadata.

        Returns:
            (ChatResponse, ResolvedModel)
        """
        # 1. 解析模型
        resolved = self.resolve_model(request.model, group_id)

        # 2. 替换为真实模型名称
        request.model = resolved.real_model_name

        # 2.5. 传递模型特性标志到请求元数据
        request.metadata['support_thinking'] = getattr(resolved.db_model, 'support_thinking', False)

        # 2.6. Convert image URLs to base64 if provider doesn't support online images
        support_online_image = getattr(resolved.db_model, 'support_online_image', True)
        if not support_online_image:
            self._convert_image_urls_to_base64(request)

        # 2.7. Convert video URLs to base64 if provider doesn't support online videos
        support_online_video = getattr(resolved.db_model, 'support_online_video', True)
        if not support_online_video:
            self._convert_video_urls_to_base64(request)

        # 3. 调用供应商 API
        try:
            response = resolved.provider_instance.chat(request)

            if not self._should_include_reasoning(request):
                for choice in response.choices:
                    choice.reasoning_content = None
                    if choice.message:
                        choice.message.reasoning_content = None

            return response, resolved
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502)
        except httpx.HTTPError as e:
            raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500)

    def chat(self, request: ChatRequest, group_id: Optional[int] = None) -> ChatResponse:
        """
        执行非流式对话请求。

        这是中间层的核心方法，它：
        1. 解析模型 → 找到正确的供应商
        2. 替换模型名称 → 使用供应商 API 需要的真实名称
        3. 调用供应商 API → 获取响应
        4. 返回统一格式的 ChatResponse

        Args:
            request: 统一的对话请求对象（由 Adapter 从任意 API 格式解析而来）
            group_id: 可选的组 ID（用于访问控制）

        Returns:
            统一的 ChatResponse 对象（由 Adapter 转换为任意 API 格式）

        Raises:
            ModelNotFoundError: 模型未找到
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # 1. 解析模型
        resolved = self.resolve_model(request.model, group_id)

        # 2. 替换为真实模型名称
        request.model = resolved.real_model_name

        # 2.5. 传递模型特性标志到请求元数据
        request.metadata['support_thinking'] = getattr(resolved.db_model, 'support_thinking', False)

        # 2.6. Convert image URLs to base64 if provider doesn't support online images
        support_online_image = getattr(resolved.db_model, 'support_online_image', True)
        if not support_online_image:
            self._convert_image_urls_to_base64(request)

        # 2.7. Convert video URLs to base64 if provider doesn't support online videos
        support_online_video = getattr(resolved.db_model, 'support_online_video', True)
        if not support_online_video:
            self._convert_video_urls_to_base64(request)

        # 3. 调用供应商 API
        try:
            response = resolved.provider_instance.chat(request)

            # 4. 根据模型能力和请求参数过滤 reasoning_content
            # 必须同时清除 choice 和 message 上的 reasoning_content，
            # 否则 Anthropic 适配器的 format_response() 会通过 message 回退获取到泄漏的推理内容
            if not self._should_include_reasoning(request):
                for choice in response.choices:
                    choice.reasoning_content = None
                    if choice.message:
                        choice.message.reasoning_content = None

            return response
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502)
        except httpx.HTTPError as e:
            raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500)

    def stream_chat(self, request: ChatRequest, group_id: Optional[int] = None) -> Generator[StreamChunk, None, None]:
        """
        执行流式对话请求。

        与 chat() 方法类似，但返回流式响应块的生成器。

        注意：模型解析（数据库访问）在此方法中立即执行（非惰性），
        以确保在 Flask 请求上下文中完成。只有流式数据传输是惰性的。

        Args:
            request: 统一的对话请求对象
            group_id: 可选的组 ID

        Returns:
            StreamChunk 生成器

        Raises:
            ModelNotFoundError: 模型未找到
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # 1. 立即解析模型（在请求上下文中访问数据库）
        resolved = self.resolve_model(request.model, group_id)

        # 2. 立即替换为真实模型名称
        request.model = resolved.real_model_name

        # 2.5. 传递模型特性标志到请求元数据
        request.metadata['support_thinking'] = getattr(resolved.db_model, 'support_thinking', False)

        # 2.6. Convert image URLs to base64 if provider doesn't support online images
        support_online_image = getattr(resolved.db_model, 'support_online_image', True)
        if not support_online_image:
            self._convert_image_urls_to_base64(request)

        # 2.7. Convert video URLs to base64 if provider doesn't support online videos
        support_online_video = getattr(resolved.db_model, 'support_online_video', True)
        if not support_online_video:
            self._convert_video_urls_to_base64(request)

        # 2.8. 判断是否应包含推理内容（在生成器外部计算，避免惰性求值问题）
        include_reasoning = self._should_include_reasoning(request)

        # 2.9. Release the DB session now that all model-resolution queries are done.
        #
        # During a streaming response the Flask request context (and therefore the
        # SQLAlchemy scoped session) remains alive for the full duration of the
        # stream.  When Flask finally tears down the app context it calls
        # db.session.remove() which triggers a rollback on the still-open
        # PyMySQL connection.  If the connection's packet-sequence counter has
        # drifted (which happens with long-lived connections under MySQL's binary
        # protocol) this raises:
        #   pymysql.err.InternalError: Packet sequence number wrong
        #
        # db.session.remove() closes the session AND removes it from the scoped
        # registry, returning the underlying connection to the pool in a clean
        # state.  Flask's subsequent session.remove() at teardown then finds no
        # registered session and completes without error.
        try:
            db.session.remove()
        except Exception:
            pass

        # 3. 返回惰性生成器（流式数据传输）
        def _stream():
            try:
                for chunk in resolved.provider_instance.stream_chat(request):
                    # 根据模型能力和请求参数过滤 reasoning_content
                    if not include_reasoning:
                        chunk.delta_reasoning_content = None
                    print(f"Yielding chunk: {chunk}")  # Debug log for each chunk
                    yield chunk
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except RuntimeError as e:
                status_code, error_data = self._parse_provider_error(e)
                raise ProviderError(str(e), status_code=status_code, error_data=error_data)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502)
            except httpx.HTTPError as e:
                raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502)
            except Exception as e:
                raise ProviderError(f"Provider error: {str(e)}", status_code=500)

        return _stream()

    def stream_chat_ex(
        self, request: ChatRequest, group_id: Optional[int] = None
    ) -> Tuple[Generator[StreamChunk, None, None], dict]:
        """
        Like stream_chat() but also returns a dict of pre-extracted primitive
        values from the resolved model/provider for usage recording.

        All ORM-object attribute reads happen *before* db.session.remove() is
        called, so no cross-session lazy-loads can occur in the caller.

        Returns:
            (StreamChunk generator, model_meta dict)

            model_meta keys:
                provider_id, provider_name, model_alias, model_real_name,
                input_price_unit, output_price_unit,
                cache_creation_price_unit, cache_token_price_unit
        """
        # 1. Resolve model (DB access)
        resolved = self.resolve_model(request.model, group_id)

        # 2. Replace with real model name
        request.model = resolved.real_model_name

        # 3. Pass model capability flags
        request.metadata['support_thinking'] = getattr(resolved.db_model, 'support_thinking', False)

        # 4. Convert image/video URLs if provider doesn't support them online
        support_online_image = getattr(resolved.db_model, 'support_online_image', True)
        if not support_online_image:
            self._convert_image_urls_to_base64(request)
        support_online_video = getattr(resolved.db_model, 'support_online_video', True)
        if not support_online_video:
            self._convert_video_urls_to_base64(request)

        # 5. Determine reasoning flag
        include_reasoning = self._should_include_reasoning(request)

        # 6. Pre-extract all primitive values from ORM objects while session is open.
        #    These will be passed to the usage recorder after db.session.remove().
        model_meta: dict = {
            'provider_id': resolved.db_provider.id,
            'provider_name': resolved.db_provider.name,
            'model_alias': resolved.db_model.alias,
            'model_real_name': resolved.db_model.name,
            'input_price_unit': getattr(resolved.db_model, 'input_price', 0.0) or 0.0,
            'output_price_unit': getattr(resolved.db_model, 'output_price', 0.0) or 0.0,
            'cache_creation_price_unit': getattr(resolved.db_model, 'cache_creation_price', 0.0) or 0.0,
            'cache_token_price_unit': getattr(resolved.db_model, 'cache_hit_price', 0.0) or 0.0,
        }

        # 7. Release the DB session — same rationale as stream_chat()
        try:
            db.session.remove()
        except Exception:
            pass

        # 8. Return lazy generator + metadata
        def _stream():
            try:
                for chunk in resolved.provider_instance.stream_chat(request):
                    if not include_reasoning:
                        chunk.delta_reasoning_content = None
                    yield chunk
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except RuntimeError as e:
                status_code, error_data = self._parse_provider_error(e)
                raise ProviderError(str(e), status_code=status_code, error_data=error_data)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                raise ProviderError(f"Connection to upstream provider failed: {str(e)}", status_code=502)
            except httpx.HTTPError as e:
                raise ProviderError(f"HTTP error from upstream provider: {str(e)}", status_code=502)
            except Exception as e:
                raise ProviderError(f"Provider error: {str(e)}", status_code=500)

        return _stream(), model_meta

    @staticmethod
    def _should_include_reasoning(request: ChatRequest) -> bool:
        """
        判断是否应在响应中包含推理内容 (reasoning_content)。

        返回 True 的条件（满足其一即可）：
        1. 模型支持思维/推理 (support_thinking 标志在数据库中为 True)
           且请求中 reasoning_effort 参数不为 'none'
        2. 请求中明确设置了 reasoning_effort（非 None 且非 'none'），
           例如通过 Responses API 的 reasoning.effort 字段传入

        Args:
            request: 对话请求对象

        Returns:
            是否应包含推理内容
        """
        reasoning_effort = request.reasoning_effort or 'none'

        # If reasoning_effort is explicitly set in the request (e.g. via Responses API),
        # always include reasoning content regardless of DB support_thinking flag
        if reasoning_effort != 'none':
            return True

        # Fall back to DB-based support_thinking flag
        support_thinking = request.metadata.get('support_thinking', False)
        return bool(support_thinking)

    def _create_provider_instance(self, db_provider: Provider) -> Optional[BaseProvider]:
        """
        根据数据库供应商配置创建供应商实例。

        Args:
            db_provider: 数据库供应商对象

        Returns:
            供应商实例，如果创建失败返回 None
        """
        provider_type = db_provider.type
        provider_class = get_provider_class(provider_type)

        if not provider_class:
            # 如果没有找到对应的供应商类，使用通用 OpenAI 兼容实现
            from app.providers.bailian import BailianProvider
            provider_class = BailianProvider

        config = ProviderConfig(
            name=db_provider.name,
            api_key=db_provider.api_key or "",
            base_url=db_provider.base_url,
            timeout=600,
            authorization=db_provider.authorization or "Authorization",
            extra_config=db_provider.extra_config or {},
        )

        try:
            return provider_class(config)
        except Exception as e:
            print(f"Error creating provider instance: {e}")
            return None

    @staticmethod
    def _convert_image_urls_to_base64(request: ChatRequest) -> None:
        """
        Convert all IMAGE_URL content blocks in the request to IMAGE_BASE64.

        Some providers (e.g. Kimi/Moonshot) do not support online image URLs in
        their API.  This method downloads each image and converts it to a base64
        data URI so the provider receives the raw image data instead.

        The conversion happens in-place on the request's messages.

        Args:
            request: The ChatRequest whose messages should be transformed.
        """
        import base64
        import logging
        import httpx
        from app.abstraction.messages import ContentBlock, ContentType

        logger = logging.getLogger("gateway")

        # Guess MIME type from Content-Type header or URL extension
        _EXT_MIME = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
        }

        def _guess_mime(url: str, content_type: str = '') -> str:
            """Determine MIME type from Content-Type header or URL extension."""
            if content_type:
                # Strip parameters like '; charset=utf-8'
                mime = content_type.split(';')[0].strip().lower()
                if mime.startswith('image/'):
                    return mime
            # Fall back to extension
            from urllib.parse import urlparse
            import os
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            return _EXT_MIME.get(ext, 'image/jpeg')

        for message in request.messages:
            if not isinstance(message.content, list):
                continue

            new_blocks = []
            for block in message.content:
                if not isinstance(block, ContentBlock):
                    new_blocks.append(block)
                    continue

                if block.type == ContentType.IMAGE_URL and block.url:
                    # Download the image and convert to base64
                    try:
                        with httpx.Client(timeout=30, follow_redirects=True) as client:
                            resp = client.get(block.url)
                            resp.raise_for_status()
                        ct = resp.headers.get('content-type', '')
                        mime = _guess_mime(block.url, ct)
                        b64_data = base64.b64encode(resp.content).decode('ascii')
                        new_blocks.append(ContentBlock.from_image_base64(b64_data, mime))
                        logger.info(
                            f"Converted image URL to base64: {block.url[:80]}... "
                            f"({len(resp.content)} bytes, {mime})"
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to download image URL {block.url[:120]}: {exc}. "
                            f"Keeping original URL block."
                        )
                        # Keep the original block if download fails
                        new_blocks.append(block)
                else:
                    new_blocks.append(block)

            message.content = new_blocks

    @staticmethod
    def _convert_video_urls_to_base64(request: ChatRequest) -> None:
        """
        Convert all VIDEO_URL content blocks in the request to VIDEO_BASE64.

        Some providers do not support online video URLs in their API.  This
        method downloads each video and converts it to a base64 data URI so the
        provider receives the raw video data instead.

        The conversion happens in-place on the request's messages.

        Args:
            request: The ChatRequest whose messages should be transformed.
        """
        import base64
        import logging
        import httpx
        from app.abstraction.messages import ContentBlock, ContentType

        logger = logging.getLogger("gateway")

        _EXT_MIME = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.ogg': 'video/ogg',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska',
            '.flv': 'video/x-flv',
            '.wmv': 'video/x-ms-wmv',
        }

        def _guess_mime(url: str, content_type: str = '') -> str:
            if content_type:
                mime = content_type.split(';')[0].strip().lower()
                if mime.startswith('video/'):
                    return mime
            from urllib.parse import urlparse
            import os
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            return _EXT_MIME.get(ext, 'video/mp4')

        for message in request.messages:
            if not isinstance(message.content, list):
                continue

            new_blocks = []
            for block in message.content:
                if not isinstance(block, ContentBlock):
                    new_blocks.append(block)
                    continue

                if block.type == ContentType.VIDEO_URL and block.url:
                    try:
                        with httpx.Client(timeout=60, follow_redirects=True) as http_client:
                            resp = http_client.get(block.url)
                            resp.raise_for_status()
                        ct = resp.headers.get('content-type', '')
                        mime = _guess_mime(block.url, ct)
                        b64_data = base64.b64encode(resp.content).decode('ascii')
                        new_blocks.append(ContentBlock.from_video_base64(b64_data, mime))
                        logger.info(
                            f"Converted video URL to base64: {block.url[:80]}... "
                            f"({len(resp.content)} bytes, {mime})"
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to download video URL {block.url[:120]}: {exc}. "
                            f"Keeping original URL block."
                        )
                        new_blocks.append(block)
                else:
                    new_blocks.append(block)

            message.content = new_blocks

    def rerank(self, request: RerankRequest, group_id: Optional[int] = None) -> RerankResponse:
        """
        执行 Rerank 请求。

        Args:
            request: Rerank 请求对象
            group_id: 可选的组 ID（用于访问控制）

        Returns:
            Rerank 响应对象

        Raises:
            ModelNotFoundError: 模型未找到
            GatewayServiceError: 供应商不支持 rerank
            ProviderError: 供应商 API 调用失败
        """
        # 1. 解析模型
        resolved = self.resolve_model(request.model, group_id)

        # 2. 替换为真实模型名称
        request.model = resolved.real_model_name

        # 3. 检查供应商是否支持 rerank
        if not hasattr(resolved.provider_instance, 'rerank'):
            raise GatewayServiceError(
                f"Provider '{resolved.db_provider.name}' does not support rerank",
                status_code=400
            )

        # 4. 调用供应商 API
        try:
            return resolved.provider_instance.rerank(request)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500)

    def embed(self, request: EmbeddingRequest, group_id: Optional[int] = None) -> EmbeddingResponse:
        """
        执行嵌入请求。

        Args:
            request: 嵌入请求对象
            group_id: 可选的组 ID（用于访问控制）

        Returns:
            嵌入响应对象

        Raises:
            ModelNotFoundError: 模型未找到
            GatewayServiceError: 请求验证失败
            ProviderError: 供应商 API 调用失败
        """
        # 1. 解析模型
        resolved = self.resolve_model(request.model, group_id)

        # 2. 替换为真实模型名称
        request.model = resolved.real_model_name

        # 2.5. 传递模型多模态能力标志到请求元数据，供 Provider 判断是否走多模态 API
        request.metadata['support_image'] = getattr(resolved.db_model, 'support_image', False)
        request.metadata['support_video'] = getattr(resolved.db_model, 'support_video', False)
        request.metadata['support_audio'] = getattr(resolved.db_model, 'support_audio', False)

        # 3. 检查模型是否标记为嵌入模型
        if not getattr(resolved.db_model, 'support_embedding', False):
            raise GatewayServiceError(
                f"Model '{resolved.db_model.alias or resolved.db_model.name}' is not an embedding model. "
                f"Set support_embedding=true for this model in the admin panel.",
                status_code=400
            )

        # 4. 检查供应商是否支持嵌入
        if not hasattr(resolved.provider_instance, 'embed'):
            raise GatewayServiceError(
                f"Provider '{resolved.db_provider.name}' does not support embedding",
                status_code=400
            )

        # 4. 调用供应商 API
        try:
            response = resolved.provider_instance.embed(request)
            return response
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)
        except Exception as e:
            raise ProviderError(f"Provider error: {str(e)}", status_code=500)

    def generate_images(
        self,
        model_name: str,
        prompt: str,
        images: Optional[list] = None,
        n: int = 1,
        size: str = "1024x1024",
        response_format: str = "url",
        output_format: str = "png",
        quality: Optional[str] = None,
        style: Optional[str] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> dict:
        """
        Execute image generation and return an OpenAI-compatible response.

        Builds a ``ChatRequest`` with image-generation metadata, routes it
        through the standard provider pipeline (which already knows how to
        detect image-generation models and metadata), then converts the
        ``ChatResponse`` to OpenAI ``/v1/images/generations`` format.

        Args:
            model_name: Model name or alias.
            prompt: Text description for the image to generate.
            n: Number of images to generate.
            size: Output image dimensions (e.g. "1024x1024").
            response_format: "url" or "b64_json".
            output_format: Image file format: "png", "jpeg", "webp".
            quality: Quality tier (provider-specific).
            style: Style preset (provider-specific).
            user: Optional end-user identifier.
            group_id: Optional group ID for access control.

        Returns:
            Dict matching the OpenAI images response schema::

                {
                    "created": <unix_ts>,
                    "data": [{"url": "...", "b64_json": "...", "revised_prompt": "..."}],
                    "output_format": "png"
                }

        Raises:
            ModelNotFoundError, GatewayServiceError, ProviderError
        """
        import json as _json
        from app.abstraction.messages import Message, MessageRole, ContentBlock

        # Build message content: text prompt + optional reference images
        if images:
            content_blocks: list = [ContentBlock.from_text(prompt)]
            for img in images:
                img_url = img.get("image_url") or img.get("url")
                if img_url:
                    content_blocks.append(ContentBlock.from_image_url(img_url))
            messages = [Message(role=MessageRole.USER, content=content_blocks)]
        else:
            messages = [Message(role=MessageRole.USER, content=prompt)]

        # These metadata keys are the same ones the Responses-API adapter sets
        # when it parses an ``image_generation`` tool.  Providers detect them
        # via ``has_image_generation_tool()`` and route to their image-gen path.
        metadata: dict = {
            "size": size,
            "number": n,
            "response_format": response_format,
            "image_format": output_format,
        }

        chat_request = ChatRequest(
            messages=messages,
            model=model_name,
            metadata=metadata,
            user=user,
        )

        # Route through the standard chat pipeline.
        # Providers that support image generation (Volcengine, Bailian, Gemini,
        # …) will detect the metadata and call their image-gen API.
        try:
            chat_response = self.chat(chat_request, group_id)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)

        # ── Convert ChatResponse → OpenAI images format ──────────────
        data: list = []
        if chat_response.choices and chat_response.choices[0].message:
            msg = chat_response.choices[0].message
            # Message.__post_init__ converts string content to
            # [ContentBlock.from_text(...)], so msg.content is always a list.
            # Use get_text_content() to retrieve the JSON string.
            text_content = msg.get_text_content()
            if text_content:
                try:
                    items = _json.loads(text_content)
                    if not isinstance(items, list):
                        items = [items]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        result = item.get("result", "")
                        img_entry: dict = {}
                        if result.startswith("data:"):
                            img_entry["b64_json"] = result
                        elif result:
                            img_entry["url"] = result
                        revised = item.get("revised_prompt")
                        if revised:
                            img_entry["revised_prompt"] = revised
                        if img_entry:
                            data.append(img_entry)
                except (_json.JSONDecodeError, TypeError):
                    pass

        return {
            "created": chat_response.created,
            "data": data,
            "output_format": output_format,
        }

    def edit_images(
        self,
        model_name: str,
        prompt: str,
        images: Optional[list] = None,
        mask: Optional[dict] = None,
        n: int = 1,
        size: str = "1024x1024",
        response_format: str = "url",
        output_format: str = "png",
        quality: Optional[str] = None,
        background: Optional[str] = None,
        input_fidelity: Optional[str] = None,
        moderation: Optional[str] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> dict:
        """
        Execute image editing and return an OpenAI-compatible response.

        Builds a ``ChatRequest`` with image-editing metadata (including
        reference images and mask), routes it through the standard provider
        pipeline, then converts the ``ChatResponse`` to the OpenAI
        ``/v1/images/edits`` response format.

        Args:
            model_name: Model name or alias.
            prompt: Text description for how to edit the image.
            images: List of input images, each dict may contain
                ``image_url`` (str) and/or ``file_id`` (str).
            mask: Optional mask image dict with ``image_url`` / ``file_id``.
            n: Number of images to generate.
            size: Output image dimensions (e.g. "1024x1024").
            response_format: "url" or "b64_json".
            output_format: Image file format: "png", "jpeg", "webp".
            quality: Quality tier (provider-specific).
            background: "transparent", "opaque", or "auto".
            input_fidelity: "high" or "low".
            moderation: "low" or "auto".
            user: Optional end-user identifier.
            group_id: Optional group ID for access control.

        Returns:
            Dict matching the OpenAI images/edits response schema.

        Raises:
            ModelNotFoundError, GatewayServiceError, ProviderError
        """
        import json as _json
        from app.abstraction.messages import Message, MessageRole, ContentBlock

        # Build message content: text prompt + reference images
        content_blocks: list = [ContentBlock.from_text(prompt)]

        if images:
            for img in images:
                img_url = img.get("image_url") or img.get("url")
                if img_url:
                    content_blocks.append(ContentBlock.from_image_url(img_url))

        messages = [Message(role=MessageRole.USER, content=content_blocks)]

        # Metadata keys recognised by image-generation providers
        metadata: dict = {
            "size": size,
            "number": n,
            "response_format": response_format,
            "image_format": output_format,
        }

        # Image-editing specific metadata
        if quality:
            metadata["quality"] = quality
        if background:
            metadata["background"] = background
        if input_fidelity:
            metadata["input_fidelity"] = input_fidelity
        if moderation:
            metadata["moderation"] = moderation
        if mask:
            metadata["mask"] = mask

        chat_request = ChatRequest(
            messages=messages,
            model=model_name,
            metadata=metadata,
            user=user,
        )

        # Route through the standard chat pipeline
        try:
            chat_response = self.chat(chat_request, group_id)
        except ValueError as e:
            raise GatewayServiceError(str(e), status_code=400)
        except RuntimeError as e:
            status_code, error_data = self._parse_provider_error(e)
            raise ProviderError(str(e), status_code=status_code, error_data=error_data)

        # ── Convert ChatResponse → OpenAI images/edits format ────────
        data: list = []
        if chat_response.choices and chat_response.choices[0].message:
            msg = chat_response.choices[0].message
            text_content = msg.get_text_content()
            if text_content:
                try:
                    items = _json.loads(text_content)
                    if not isinstance(items, list):
                        items = [items]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        result = item.get("result", "")
                        img_entry: dict = {}
                        if result.startswith("data:"):
                            img_entry["b64_json"] = result
                        elif result:
                            img_entry["url"] = result
                        revised = item.get("revised_prompt")
                        if revised:
                            img_entry["revised_prompt"] = revised
                        if img_entry:
                            data.append(img_entry)
                except (_json.JSONDecodeError, TypeError):
                    pass

        result_dict: dict = {
            "created": chat_response.created,
            "data": data,
            "output_format": output_format,
            "size": size,
        }
        if quality:
            result_dict["quality"] = quality
        if background and background != "auto":
            result_dict["background"] = background

        return result_dict

    @staticmethod
    def _parse_provider_error(error: RuntimeError) -> Tuple[int, Optional[dict]]:
        """
        解析供应商错误，提取状态码和错误数据。

        Args:
            error: 供应商抛出的 RuntimeError

        Returns:
            (status_code, error_data) 元组
        """
        import re
        import json

        error_msg = str(error)
        match = re.search(r'API error \((\d+)\)', error_msg)

        if match:
            status_code = int(match.group(1))
            try:
                json_start = error_msg.find('): ') + 3
                if json_start > 2:
                    json_str = error_msg[json_start:]
                    error_data = json.loads(json_str)
                    return status_code, error_data
            except (json.JSONDecodeError, ValueError):
                pass
            return status_code, None

        return 500, None
