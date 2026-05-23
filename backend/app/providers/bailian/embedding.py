"""
阿里云百炼嵌入模块 (Bailian Embedding)

支持两种嵌入模式：
1. 文本嵌入（OpenAI 兼容格式）：复用 OpenAIProvider，走 /compatible-mode/v1/embeddings
2. 多模态嵌入（百炼专用格式）：走专用 Dashscope API，支持文本、图片、视频混合输入

多模态嵌入 API 文档:
https://help.aliyun.com/document_detail/2712576.html

多模态嵌入请求格式：
POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
{
    "model": "qwen3-vl-embedding",
    "input": {
        "contents": [
            {"text": "文本内容"},
            {"image": "https://..."},
            {"image": "https://..."},
            {"video": "https://..."}
        ]
    },
    "parameters": {
        "enable_fusion": true
    }
}

多模态嵌入响应格式：
{
    "output": {
        "embeddings": [
            {"index": 0, "embedding": [...], "type": "text"},
            {"index": 1, "embedding": [...], "type": "image"}
        ]
    },
    "usage": {
        "input_tokens": 10,
        "image_tokens": 896
    }
}
"""
from typing import List, Dict, Any
import json
import sys

import httpx

from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse, EmbeddingData, EmbeddingUsage


# =============================================================================
# 消息转换 - OpenAI messages → 百炼 contents
# =============================================================================

def convert_messages_to_bailian_contents(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 OpenAI 格式的 messages 转换为百炼多模态嵌入的 contents 格式。

    输入格式 (OpenAI messages):
    [{"role": "user", "content": [
        {"type": "text", "text": "描述"},
        {"type": "image_url", "image_url": {"url": "https://..."}},
        {"type": "video_url", "video_url": {"url": "https://..."}}
    ]}]

    输出格式 (百炼 Dashscope contents)：每张图片单独一项（不合并为 multi_images）
    [
        {"text": "描述"},
        {"image": "https://..."},
        {"video": "https://..."}
    ]

    Args:
        messages: OpenAI 格式的消息列表

    Returns:
        百炼格式的 contents 列表
    """
    contents: List[Dict[str, Any]] = []

    for message in messages:
        content = message.get("content", [])

        if isinstance(content, str):
            contents.append({"text": content})
            continue

        if isinstance(content, list):
            for item in content:
                item_type = item.get("type", "text")

                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        contents.append({"text": text})
                elif item_type == "image_url":
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")
                    if url:
                        contents.append({"image": url})
                elif item_type == "video_url":
                    video_url = item.get("video_url", {})
                    url = video_url.get("url", "")
                    if url:
                        contents.append({"video": url})

    return contents


# =============================================================================
# 响应解析
# =============================================================================

def parse_bailian_multimodal_embedding_response(
    data: Dict[str, Any], model: str
) -> EmbeddingResponse:
    """
    解析百炼多模态嵌入响应。

    Args:
        data: 百炼 API 响应数据
        model: 模型名称

    Returns:
        统一的嵌入响应对象
    """
    embedding_data = []
    output = data.get("output", {})

    for item in output.get("embeddings", []):
        embedding_data.append(EmbeddingData(
            index=item.get("index", 0),
            embedding=item.get("embedding", []),
            object="embedding"
        ))

    usage_data = data.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    image_tokens = usage_data.get("image_tokens", 0)
    video_tokens = usage_data.get("video_tokens", 0)
    total_tokens = input_tokens + image_tokens + video_tokens

    usage = EmbeddingUsage(
        prompt_tokens=total_tokens,
        total_tokens=total_tokens
    )

    return EmbeddingResponse(
        object="list",
        data=embedding_data,
        model=model,
        usage=usage
    )


# =============================================================================
# 多模态嵌入 API 调用
# =============================================================================

async def execute_bailian_multimodal_embed(
    api_key: str,
    multimodal_embedding_url: str,
    request: EmbeddingRequest,
) -> EmbeddingResponse:
    """
    执行百炼多模态嵌入请求。

    将 OpenAI messages 格式转换为 Dashscope contents 格式：
    - text          → {"text": "..."}
    - image_url.url → {"image": "..."}
    - video_url.url → {"video": "..."}

    Args:
        api_key: 百炼 API Key
        multimodal_embedding_url: 多模态嵌入 API 端点 URL
        request: 嵌入请求对象

    Returns:
        嵌入响应对象

    Raises:
        RuntimeError: API 调用失败时抛出
    """
    contents = convert_messages_to_bailian_contents(request.messages)

    parameters: Dict[str, Any] = {"enable_fusion": True}
    if request.dimensions:
        parameters["dimension"] = request.dimensions

    request_data: Dict[str, Any] = {
        "model": request.model,
        "input": {
            "contents": contents
        },
        "parameters": parameters,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(multimodal_embedding_url, json=request_data, headers=headers)

        if response.status_code >= 400:
            try:
                error_data = response.json()
                raise RuntimeError(
                    f"Bailian multimodal embedding API error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )
            except (json.JSONDecodeError, RuntimeError) as e:
                if isinstance(e, RuntimeError):
                    raise
                raise RuntimeError(
                    f"Bailian multimodal embedding API error ({response.status_code}): "
                    f"{response.text}"
                )

        response_data = response.json()
        return parse_bailian_multimodal_embedding_response(response_data, request.model)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Bailian multimodal embedding API error: {str(e)}")
