"""
阿里云百炼 Rerank 模块 (Bailian Rerank)

支持两种 Rerank 模式：
1. 文本 Rerank（OpenAI 兼容格式）：走 /compatible-mode/v1/reranks（或 /compatible-api/v1/reranks）
2. 多模态 Rerank（百炼专用格式）：走专用 Dashscope API，支持文本、图片、视频混合输入

文本 Rerank API（兼容模式）：
POST https://dashscope.aliyuncs.com/compatible-mode/v1/reranks
Authorization: Bearer $DASHSCOPE_API_KEY
{
    "model": "qwen3-rerank",
    "query": "什么是文本排序模型",
    "documents": ["文本一", "文本二"],
    "top_n": 2,
    "instruct": "..."
}

多模态 Rerank API（Dashscope 专用）：
POST https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
Authorization: Bearer $DASHSCOPE_API_KEY
{
    "model": "qwen3-vl-rerank",
    "input": {
        "query": {"text": "..."} | {"image": "..."} | {"video": "..."},
        "documents": [{"text": "..."}, {"image": "..."}, {"video": "..."}]
    },
    "parameters": {
        "return_documents": true,
        "top_n": 2,
        "fps": 1.0
    }
}
"""
from typing import List, Dict, Any, Optional
import json
import sys

import httpx

from app.abstraction.rerank import (
    RerankRequest,
    RerankResponse,
    RerankResult,
    RerankDocument,
    RerankUsage,
)
from app.utils import gen_id


# =============================================================================
# 文本 Rerank — 兼容模式 API
# =============================================================================

async def execute_bailian_text_rerank(
    api_key: str,
    rerank_url: str,
    request: RerankRequest,
) -> RerankResponse:
    """
    执行百炼文本 Rerank 请求（兼容模式）。

    使用 /compatible-mode/v1/reranks 端点，格式与 OpenAI/Cohere rerank API 兼容。

    百炼请求格式：
    {
        "model": "qwen3-rerank",
        "query": "...",
        "documents": ["文本一", "文本二"],
        "top_n": 2,
        "instruct": "..."
    }

    百炼响应格式：
    {
        "output": {
            "results": [
                {"document": {"text": "..."}, "index": 0, "relevance_score": 0.93}
            ]
        },
        "usage": {"total_tokens": 79},
        "request_id": "..."
    }

    Args:
        api_key: 百炼 API Key
        rerank_url: Rerank API 端点 URL（如 /compatible-mode/v1/reranks）
        request: 统一的 RerankRequest 对象

    Returns:
        统一的 RerankResponse 对象

    Raises:
        RuntimeError: API 调用失败时抛出
    """
    # 将 documents 规范化为纯文本列表
    documents = [
        d["text"] if isinstance(d, dict) and "text" in d else str(d)
        for d in request.documents
    ]

    request_data: Dict[str, Any] = {
        "model": request.model,
        "query": request.query if isinstance(request.query, str) else request.query.get("text", ""),
        "documents": documents,
        "parameters": {
            "return_documents": True,
        }
    }
    request_data['return_documents'] = True
    if request.top_n is not None:
        request_data["top_n"] = request.top_n
        request_data["parameters"]["top_n"] = request.top_n
    if request.instruct:
        request_data["instruct"] = request.instruct
        request_data["parameters"]["instruct"] = request.instruct

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(rerank_url, json=request_data, headers=headers)

        if response.status_code >= 400:
            _raise_api_error("Bailian text rerank", response)

        response_data = response.json()
        return _parse_bailian_rerank_response(response_data, request.model, request.return_documents)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Bailian text rerank API error: {str(e)}")


# =============================================================================
# 多模态 Rerank — Dashscope 专用 API
# =============================================================================

async def execute_bailian_multimodal_rerank(
    api_key: str,
    multimodal_rerank_url: str,
    request: RerankRequest,
) -> RerankResponse:
    """
    执行百炼多模态 Rerank 请求（Dashscope 专用格式）。

    支持文本、图片、视频混合输入的 rerank。

    百炼请求格式：
    {
        "model": "qwen3-vl-rerank",
        "input": {
            "query": {"text": "..."} | {"image": "..."} | {"video": "..."},
            "documents": [{"text": "..."}, {"image": "..."}, {"video": "..."}]
        },
        "parameters": {
            "return_documents": true,
            "top_n": 2,
            "fps": 1.0
        }
    }

    百炼响应格式：
    {
        "output": {
            "results": [
                {"document": {"image": "..."}, "index": 1, "relevance_score": 0.88}
            ]
        },
        "usage": {"image_tokens": 3880, "input_tokens": 207, "total_tokens": 4087},
        "request_id": "..."
    }

    Args:
        api_key: 百炼 API Key
        multimodal_rerank_url: 多模态 Rerank API 端点 URL
        request: 统一的 RerankRequest 对象

    Returns:
        统一的 RerankResponse 对象

    Raises:
        RuntimeError: API 调用失败时抛出
    """
    # 规范化 query
    query = request.query if isinstance(request.query, dict) else {"text": request.query}

    # 规范化 documents
    documents = [
        d if isinstance(d, dict) else {"text": d}
        for d in request.documents
    ]

    parameters: Dict[str, Any] = {
        "return_documents": request.return_documents,
    }
    if request.top_n is not None:
        parameters["top_n"] = request.top_n

    request_data: Dict[str, Any] = {
        "model": request.model,
        "input": {
            "query": query,
            "documents": documents,
        },
        "parameters": parameters,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(multimodal_rerank_url, json=request_data, headers=headers)

        if response.status_code >= 400:
            _raise_api_error("Bailian multimodal rerank", response)

        response_data = response.json()
        return _parse_bailian_rerank_response(response_data, request.model, request.return_documents)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Bailian multimodal rerank API error: {str(e)}")


# =============================================================================
# 响应解析（兼容两种格式）
# =============================================================================

def _parse_bailian_rerank_response(
    data: Dict[str, Any],
    model: str,
    return_documents: bool,
) -> RerankResponse:
    """
    解析百炼 Rerank 响应（兼容两种响应格式）。

    兼容模式（compatible-api）响应格式：results 在顶层
    {
        "results": [
            {"document": {"text": "..."}, "index": 0, "relevance_score": 0.93}
        ],
        "usage": {"total_tokens": 79}
    }

    Dashscope 原生格式：results 嵌套在 output 下
    {
        "output": {
            "results": [
                {"document": {"text": "..."}, "index": 0, "relevance_score": 0.93}
            ]
        },
        "usage": {"total_tokens": 79}
    }

    Args:
        data: 百炼 API 响应数据
        model: 模型名称
        return_documents: 是否在结果中包含文档内容

    Returns:
        统一的 RerankResponse 对象
    """
    # 优先从顶层取 results（compatible-api 格式），其次从 output.results 取（Dashscope 原生格式）
    raw_results = data.get("results") or data.get("output", {}).get("results", [])

    results: List[RerankResult] = []
    for item in raw_results:
        doc_data = item.get("document", {})
        doc: Optional[RerankDocument] = None
        if return_documents and doc_data:
            doc = RerankDocument(
                text=doc_data.get("text"),
                image=doc_data.get("image"),
                video=doc_data.get("video"),
            )
        results.append(RerankResult(
            index=item.get("index", 0),
            relevance_score=item.get("relevance_score", 0.0),
            document=doc,
        ))

    usage_data = data.get("usage", {})
    total_tokens = usage_data.get("total_tokens", 0)
    usage = RerankUsage(total_tokens=total_tokens)

    return RerankResponse(
        id=gen_id("rerank"),
        model=model,
        results=results,
        usage=usage,
    )


# =============================================================================
# 工具函数
# =============================================================================


def _raise_api_error(prefix: str, response: httpx.Response) -> None:
    """从 HTTP 响应构造 RuntimeError 并抛出。"""
    try:
        error_data = response.json()
        raise RuntimeError(
            f"{prefix} API error ({response.status_code}): "
            f"{json.dumps(error_data, ensure_ascii=False)}"
        )
    except (json.JSONDecodeError, RuntimeError) as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(
            f"{prefix} API error ({response.status_code}): {response.text}"
        )
