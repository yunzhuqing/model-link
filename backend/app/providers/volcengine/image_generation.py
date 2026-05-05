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
from typing import Optional, List, Dict, Any

import httpx
import json


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
        response_format: str = "url",
        image_format: str = "png",
        seed: Optional[int] = None,
        reference_images: Optional[List[str]] = None,
        watermark: bool = False,
        support_output_format: bool = True,
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
            support_output_format: 是否支持 output_format 参数（5.0+支持，4.x 不支持）

        Returns:
            包含生成图像结果的字典
        """
        # 构造请求体（使用真实 API 字段名）
        # Always request URL format from the Doubao API; the caller is responsible
        # for converting to base64 when response_format="b64_json" is requested.
        request_body: Dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "response_format": "url",        # Always request URL; upper layer converts if needed
            "watermark": watermark,
        }

        # 只有支持 output_format 参数的模型才添加此字段
        if support_output_format:
            request_body["output_format"] = image_format

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


def is_doubao_image_model(model_name: str) -> bool:
    """
    检查是否为豆包图像生成模型
    
    Args:
        model_name: 模型名称
    
    Returns:
        是否为豆包图像生成模型
    """
    model_name_lower = model_name.lower()
    # 检查是否包含 doubao-seedream 或 seedream
    return "doubao-seedream" in model_name_lower or model_name_lower.startswith("seedream")


def get_support_output_format(model_name: str) -> bool:
    """
    检查模型是否支持 output_format 参数
    
    5.0 及之后的版本支持，5.0 之前的版本（4.x、3.x 等）不支持。
    
    通过从模型名称中提取主版本号来判断：
    - seedream-5-0, seedream-5.0, seedream-6-0 等 → 支持
    - seedream-4-0, seedream-4-5, seedream-3-0 等 → 不支持
    
    Args:
        model_name: 模型名称
    
    Returns:
        是否支持 output_format 参数
    """
    import re
    model_name_lower = model_name.lower()
    # 从模型名称中提取 seedream 后面的主版本号
    # 匹配模式: seedream-X.Y 或 seedream-X-Y（X 是主版本号）
    match = re.search(r'seedream[- ]?(\d+)[.\-]', model_name_lower)
    if match:
        major_version = int(match.group(1))
        return major_version >= 5
    return False
