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

        # 3. 调用供应商 API
        try:
            response = resolved.provider_instance.chat(request)
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

        # 3. 返回惰性生成器（流式数据传输）
        def _stream():
            try:
                for chunk in resolved.provider_instance.stream_chat(request):
                    yield chunk
            except ValueError as e:
                raise GatewayServiceError(str(e), status_code=400)
            except RuntimeError as e:
                status_code, error_data = self._parse_provider_error(e)
                raise ProviderError(str(e), status_code=status_code, error_data=error_data)
            except Exception as e:
                raise ProviderError(f"Provider error: {str(e)}", status_code=500)

        return _stream()

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
        )

        try:
            return provider_class(config)
        except Exception as e:
            print(f"Error creating provider instance: {e}")
            return None

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
