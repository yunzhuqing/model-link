"""
中间层 (Middleware Layer)
提供网关服务，隐藏供应商 API 细节，统一处理请求路由和响应转换。
"""

from .gateway_service import GatewayService

__all__ = ['GatewayService']
