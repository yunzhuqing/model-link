"""
火山引擎多模态嵌入模块 (Volcengine Multimodal Embedding)

API: POST /api/v3/embeddings/multimodal
文档: https://www.volcengine.com/docs/82379/1399008

多模态嵌入请求格式：
POST https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal
{
    "model": "doubao-embedding-vision-251215",
    "encoding_format": "float",
    "input": [
        {"type": "video_url", "video_url": {"url": "https://..."}},
        {"type": "image_url", "image_url": {"url": "https://..."}},
        {"type": "text", "text": "描述内容"}
    ]
}

多模态嵌入响应格式：
{
    "created": 1752133360,
    "data": {
        "embedding": [...],
        "sparse_embedding": [{"index": 1, "value": 0.0887}, ...],
        "object": "embedding"
    },
    "id": "...",
    "model": "...",
    "object": "list",
    "usage": {
        "prompt_tokens": 25,
        "prompt_tokens_details": {"image_tokens": 0, "text_tokens": 25},
        "total_tokens": 25
    }
}
"""
from typing import List, Dict, Any, Union, Optional
import json

import httpx

from app.http_client import shared_client

from app.abstraction.embedding import EmbeddingRequest, EmbeddingResponse, EmbeddingData, EmbeddingUsage


def convert_messages_to_volcengine_input(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 OpenAI 格式的 messages 转换为火山引擎多模态嵌入的 input 格式。

    输入: [{"role": "user", "content": [{"type": "text", "text": "..."}, ...]}]
    输出: [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}, ...]
    """
    input_blocks: List[Dict[str, Any]] = []

    for message in messages:
        content = message.get("content", [])

        if isinstance(content, str):
            input_blocks.append({"type": "text", "text": content})
            continue

        if isinstance(content, list):
            for item in content:
                item_type = item.get("type", "")

                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        input_blocks.append({"type": "text", "text": text})
                elif item_type == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url:
                        input_blocks.append({"type": "image_url", "image_url": {"url": url}})
                elif item_type == "video_url":
                    url = item.get("video_url", {}).get("url", "")
                    if url:
                        input_blocks.append({"type": "video_url", "video_url": {"url": url}})

    return input_blocks


def convert_text_to_volcengine_input(input_data: Union[str, List[str]]) -> List[Dict[str, Any]]:
    """将纯文本输入转换为火山引擎 input 格式。"""
    if isinstance(input_data, str):
        return [{"type": "text", "text": input_data}]
    return [{"type": "text", "text": t} for t in input_data if t]


def parse_volcengine_multimodal_embedding_response(
    data: Dict[str, Any], model: str
) -> EmbeddingResponse:
    """
    解析火山引擎多模态嵌入响应。

    火山引擎返回单个 data 对象（非数组），包含一个融合后的 embedding 向量。
    """
    embedding_list = []
    inner_data = data.get("data", {})

    embeddings = inner_data.get("embedding", [])
    embedding_list.append(EmbeddingData(
        index=0,
        embedding=embeddings,
        object="embedding"
    ))

    usage_data = data.get("usage", {})
    usage = EmbeddingUsage(
        prompt_tokens=usage_data.get("prompt_tokens", 0),
        total_tokens=usage_data.get("total_tokens", 0)
    )

    return EmbeddingResponse(
        object="list",
        data=embedding_list,
        model=model,
        usage=usage
    )


async def execute_volcengine_multimodal_embed(
    api_key: str,
    base_url: str,
    request: EmbeddingRequest,
    tracer: Optional[Any] = None,
) -> EmbeddingResponse:
    """
    执行火山引擎多模态嵌入请求。

    将 OpenAI messages 或纯文本 input 转换为火山引擎的 input 格式，
    然后调用 /embeddings/multimodal 端点。
    """
    if request.messages:
        input_blocks = convert_messages_to_volcengine_input(request.messages)
    elif request.input is not None:
        input_blocks = convert_text_to_volcengine_input(request.input)
    else:
        raise ValueError("No input or messages provided in embedding request")

    request_data: Dict[str, Any] = {
        "model": request.model,
        "encoding_format": request.encoding_format,
        "input": input_blocks,
    }

    if request.dimensions:
        request_data["dimensions"] = request.dimensions

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    url = f"{base_url}/embeddings/multimodal"

    child_span = None
    if tracer:
        child_span = tracer.start_child(
            request.model, model=request.model,
            provider_type="volcengine", input_data=request_data
        )
        if child_span:
            child_span.log_input(request_data)

    try:
        async with shared_client() as client:
            response = await client.post(url, json=request_data, headers=headers)

        if response.status_code >= 400:
            try:
                error_data = response.json()
                raise RuntimeError(
                    f"Volcengine embedding API error ({response.status_code}): "
                    f"{json.dumps(error_data, ensure_ascii=False)}"
                )
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Volcengine embedding API error ({response.status_code}): "
                    f"{response.text}"
                )

        response_data = response.json()
        if child_span:
            child_span.log_output(response_data)
        return parse_volcengine_multimodal_embedding_response(response_data, request.model)

    except RuntimeError:
        if child_span:
            child_span.end(error=RuntimeError)
        raise
    except Exception as e:
        if child_span:
            child_span.end(error=e)
        raise RuntimeError(f"Volcengine embedding API error: {str(e)}")