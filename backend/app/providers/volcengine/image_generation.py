"""
豆包图像生成工具模块 (Doubao Image Generation)

豆包图像生成模型可以通过 Responses API 作为 image_generation 类型的工具进行调用。
支持的模型包括：
- doubao-seedream-4.0/4.5/5.0: 支持顺序图像生成
- seedream-4.0/4.5/5.0: 同上（无 doubao 前缀）

已废弃（不再支持）：
- doubao-seedream-3.0-t2i
- doubao-seededit-3.0-i2i

API 文档: https://www.volcengine.com/docs/82379/181798
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Generator
from enum import Enum

from app.abstraction.tools import ToolDefinition, ToolParameter, ToolType
from app.abstraction.chat import ChatRequest, ChatResponse, ChatChoice, UsageInfo, FinishReason
from app.abstraction.messages import Message, MessageRole, ContentBlock
from app.abstraction.streaming import StreamChunk, StreamEventType


# =============================================================================
# 图像生成模型配置
# =============================================================================

@dataclass
class DoubaoImageModel:
    """豆包图像生成模型配置"""
    model_name: str  # API 实际使用的模型名称
    display_name: str  # 显示名称
    tool_name: str  # 工具名称（用于 tool_choice）
    description: str  # 模型描述
    support_seed: bool = False  # 是否支持种子参数
    support_guidance_scale: bool = False  # 是否支持引导强度
    default_guidance_scale: float = 3.5  # 默认引导强度
    support_sequential_image: bool = False  # 是否支持顺序图像生成（多轮对话）


# 豆包图像生成模型列表（已废弃：doubao-seedream-3.0-t2i、doubao-seededit-3.0-i2i）
DOUBAO_IMAGE_MODELS: List[DoubaoImageModel] = [
    DoubaoImageModel(
        model_name="doubao-seedream-4.0",
        display_name="Seedream 4.0",
        tool_name="image_generation_doubao_seedream_4_0",
        description="豆包 Seedream 4.0，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
    DoubaoImageModel(
        model_name="doubao-seedream-4.5",
        display_name="Seedream 4.5",
        tool_name="image_generation_doubao_seedream_4_5",
        description="豆包 Seedream 4.5，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
    DoubaoImageModel(
        model_name="doubao-seedream-5.0",
        display_name="Seedream 5.0",
        tool_name="image_generation_doubao_seedream_5_0",
        description="豆包 Seedream 5.0，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
    DoubaoImageModel(
        model_name="seedream-4.0",
        display_name="Seedream 4.0 (无前缀)",
        tool_name="image_generation_seedream_4_0",
        description="Seedream 4.0，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
    DoubaoImageModel(
        model_name="seedream-4.5",
        display_name="Seedream 4.5 (无前缀)",
        tool_name="image_generation_seedream_4_5",
        description="Seedream 4.5，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
    DoubaoImageModel(
        model_name="seedream-5.0",
        display_name="Seedream 5.0 (无前缀)",
        tool_name="image_generation_seedream_5_0",
        description="Seedream 5.0，支持多轮顺序图像生成",
        support_sequential_image=True,
    ),
]


def get_doubao_image_model(model_name: str) -> Optional[DoubaoImageModel]:
    """
    根据模型名称获取豆包图像生成模型配置
    
    Args:
        model_name: 模型名称（可以是完整名称或部分匹配）
    
    Returns:
        模型配置，如果未找到返回 None
    """
    model_name_lower = model_name.lower()
    
    # 精确匹配
    for model in DOUBAO_IMAGE_MODELS:
        if model.model_name.lower() == model_name_lower:
            return model
    
    # 部分匹配
    for model in DOUBAO_IMAGE_MODELS:
        if model.model_name.lower() in model_name_lower or model_name_lower in model.model_name.lower():
            return model
    
    return None


def list_doubao_image_models() -> List[DoubaoImageModel]:
    """列出所有豆包图像生成模型"""
    return DOUBAO_IMAGE_MODELS.copy()


# =============================================================================
# 图像生成工具定义
# =============================================================================

def create_image_generation_tool(model: DoubaoImageModel) -> ToolDefinition:
    """
    为豆包图像生成模型创建工具定义
    
    Args:
        model: 豆包图像生成模型配置
    
    Returns:
        工具定义
    """
    parameters: List[ToolParameter] = [
        ToolParameter(
            name="prompt",
            type="string",
            description="图像生成/编辑的文本描述",
            required=True
        ),
        ToolParameter(
            name="image_size",
            type="string",
            description="输出图像尺寸，如 '1024x1024', '768x1344', '1344x768', '1536x1024', '1024x1536'",
            required=False,
            default="1024x1024",
            enum=["1024x1024", "768x1344", "1344x768", "1536x1024", "1024x1536", "1440x720", "720x1440"]
        ),
        ToolParameter(
            name="number",
            type="integer",
            description="生成图像数量，1-4",
            required=False,
            default=1
        ),
        ToolParameter(
            name="output_format",
            type="string",
            description="输出格式",
            required=False,
            default="base64",
            enum=["base64", "url"]
        ),
    ]
    
    # 如果模型支持 seed 参数
    if model.support_seed:
        parameters.append(ToolParameter(
            name="seed",
            type="integer",
            description="随机种子，用于生成可复现的图像",
            required=False
        ))
    
    # 如果模型支持引导强度
    if model.support_guidance_scale:
        parameters.append(ToolParameter(
            name="guidance_scale",
            type="number",
            description=f"引导强度，范围 0.1-10.0，默认 {model.default_guidance_scale}",
            required=False,
            default=model.default_guidance_scale
        ))
    
    return ToolDefinition(
        name=model.tool_name,
        description=model.description,
        parameters=parameters,
        tool_type=ToolType.IMAGE_GENERATION
    )


def get_image_generation_tools() -> List[ToolDefinition]:
    """
    获取所有豆包图像生成工具定义
    
    Returns:
        工具定义列表
    """
    return [create_image_generation_tool(model) for model in DOUBAO_IMAGE_MODELS]


# =============================================================================
# 图像生成工具调用结果处理
# =============================================================================

class DoubaoImageProvider:
    """
    豆包图像生成工具执行器
    
    通过 Responses API 调用豆包图像生成模型。
    当 LLM 调用图像生成工具时，此类负责：
    1. 构造符合 Responses API 格式的请求
    2. 调用 API 获取生成的图像
    3. 返回结构化的图像结果
    """
    
    PROVIDER_TYPE: str = "volcengine_image"
    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        """
        初始化图像生成工具执行器
        
        Args:
            api_key: API 密钥
            base_url: 可选的 API 基础 URL
        """
        self.api_key = api_key
        self.base_url = base_url or self.DEFAULT_BASE_URL
        
        # Ensure base_url ends with /v3
        if not self.base_url.endswith("/v3") and "/v3/" not in self.base_url:
            self.base_url = self.base_url.rstrip("/") + "/v3"
    
    def generate_image(
        self,
        model_name: str,
        prompt: str,
        size: str = "1024x1024",
        number: int = 1,
        response_format: str = "b64_json",
        image_format: str = "png",
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        watermark: bool = False,
    ) -> Dict[str, Any]:
        """
        调用豆包图像生成 API

        API 文档: https://www.volcengine.com/docs/82379/181798

        Args:
            model_name: 图像生成模型名称（如 "doubao-seedream-5-0-260128"）
            prompt: 图像描述文字
            size: 输出图像尺寸，如 "1024x1024"、"2K"
            number: 生成图像数量（>1 时启用 sequential_image_generation）
            response_format: 返回格式，"url" 或 "b64_json"
            image_format: 图像文件格式，如 "png"、"jpg"
            seed: 随机种子
            reference_images: 参考图像 URL 列表（用于图生图）
            watermark: 是否添加水印

        Returns:
            包含生成图像结果的字典
        """
        import httpx
        import json

        # 构造请求体（使用真实 API 字段名）
        # Always request URL format from the Doubao API; the caller is responsible
        # for converting to base64 when response_format="b64_json" is requested.
        request_body: Dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "output_format": image_format,   # 图像文件格式：png / jpg
            "response_format": "url",        # Always request URL; upper layer converts if needed
            "watermark": watermark,
        }

        if size:
            request_body["size"] = size

        if seed is not None:
            request_body["seed"] = seed

        # 参考图像（图生图场景）
        if reference_images:
            request_body["image"] = reference_images
            # 有参考图时禁用顺序生成，避免参数冲突
            request_body["sequential_image_generation"] = "disabled"

        # 多图生成：启用顺序图像生成
        if number > 1:
            request_body["sequential_image_generation"] = "auto"
            request_body["sequential_image_generation_options"] = {
                "max_images": number
            }

        # 调用 API
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            with httpx.Client(timeout=300) as client:
                response = client.post(
                    f"{self.base_url}/images/generations",
                    json=request_body,
                    headers=headers
                )

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        raise RuntimeError(
                            f"Doubao Image API error ({response.status_code}): "
                            f"{json.dumps(error_data, ensure_ascii=False)}"
                        )
                    except json.JSONDecodeError:
                        raise RuntimeError(
                            f"Doubao Image API error ({response.status_code}): {response.text}"
                        )

                return response.json()

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Doubao Image API error: {str(e)}")
    
    def parse_image_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        解析图像生成 API 响应
        
        Args:
            response_data: API 响应数据
        
        Returns:
            图像结果列表
        """
        images = []
        
        # 尝试从不同的响应格式中提取图像
        # 格式1: {"data": [{"url": "...", "base64": "..."}]}
        if "data" in response_data:
            for item in response_data["data"]:
                if "url" in item:
                    images.append({
                        "url": item["url"],
                        "revised_prompt": item.get("revised_prompt")
                    })
                elif "b64_json" in item:
                    images.append({
                        "base64": item["b64_json"],
                        "revised_prompt": item.get("revised_prompt")
                    })
        
        # 格式2: {"output": {"images": [...]}
        elif "output" in response_data:
            output = response_data["output"]
            if "images" in output:
                for item in output["images"]:
                    if isinstance(item, dict):
                        images.append(item)
                    elif isinstance(item, str):
                        # 可能是 base64 字符串
                        if len(item) > 100:  # 可能是 base64
                            images.append({"base64": item})
        
        # 格式3: 直接是 images 数组
        elif "images" in response_data:
            for item in response_data["images"]:
                if isinstance(item, dict):
                    images.append(item)
        
        return images


# =============================================================================
# 便捷函数
# =============================================================================

def get_image_generation_tool_definition(model_name: str) -> Optional[ToolDefinition]:
    """
    根据模型名称获取图像生成工具定义
    
    Args:
        model_name: 模型名称
    
    Returns:
        工具定义，如果未找到返回 None
    """
    model = get_doubao_image_model(model_name)
    if model:
        return create_image_generation_tool(model)
    return None


def is_doubao_image_model(model_name: str) -> bool:
    """
    检查是否为豆包图像生成模型
    
    Args:
        model_name: 模型名称
    
    Returns:
        是否为豆包图像生成模型
    """
    return get_doubao_image_model(model_name) is not None


def get_tool_name_for_model(model_name: str) -> Optional[str]:
    """
    根据模型名称获取对应的工具名称
    
    Args:
        model_name: 模型名称
    
    Returns:
        工具名称，如果未找到返回 None
    """
    model = get_doubao_image_model(model_name)
    if model:
        return model.tool_name
    return None
