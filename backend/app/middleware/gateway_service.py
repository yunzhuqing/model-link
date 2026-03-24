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
from typing import Optional, Generator, Tuple
from dataclasses import dataclass

from app import db
from app.models import Provider, Model
from app.providers import get_provider_class
from app.providers.base import BaseProvider, ProviderConfig
from app.abstraction.chat import ChatRequest, ChatResponse
from app.abstraction.streaming import StreamChunk


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
        db_model = db.session.query(Model).filter(
            (Model.alias == model_name) | (Model.name == model_name)
        ).first()

        if not db_model:
            raise ModelNotFoundError(model_name)

        db_provider = db.session.query(Provider).filter(
            Provider.id == db_model.provider_id
        ).first()

        if not db_provider:
            raise ModelNotFoundError(model_name)

        # 检查组访问权限
        if group_id is not None and db_provider.group_id != group_id:
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

        # 3. 返回惰性生成器（流式数据传输）
        def _stream():
            try:
                for chunk in resolved.provider_instance.stream_chat(request):
                    # 根据模型能力和请求参数过滤 reasoning_content
                    if not include_reasoning:
                        chunk.delta_reasoning_content = None
                    yield chunk
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except RuntimeError as e:
                status_code, error_data = self._parse_provider_error(e)
                raise ProviderError(str(e), status_code=status_code, error_data=error_data)
            except Exception as e:
                raise ProviderError(f"Provider error: {str(e)}", status_code=500)

        return _stream()

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
            from app.providers.bailian_provider import BailianProvider
            provider_class = BailianProvider

        config = ProviderConfig(
            name=db_provider.name,
            api_key=db_provider.api_key or "",
            base_url=db_provider.base_url,
            timeout=60,
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
