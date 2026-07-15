"""
JSON Schema 工具函数 (Schema Utilities)

供各 provider 共享的 JSON Schema 处理逻辑。
"""
from typing import Any, Dict


def inline_jsonschema_refs(schema: Any) -> Any:
    """递归内联 JSON Schema 中的 $ref 引用。

    部分供应商（如 Gemini）不支持 JSON Schema 的 ``$ref`` / ``$defs`` /
    ``definitions`` 引用，需要把引用内联展开为完整结构后再下发。

    本方法解析本地引用（``#/$defs/...``、``#/definitions/...``）并就地替换，
    然后移除 ``$defs`` / ``definitions`` / ``additionalProperties`` 这些供应商
    不支持的键。无法解析的非本地引用保留原样交给下游处理。

    做了循环引用防护：同一条解析路径上重复出现的引用会被截断，避免无限递归。

    Args:
        schema: JSON Schema 对象或任意值

    Returns:
        完全内联、清理后的 schema
    """
    if not isinstance(schema, dict):
        return schema

    defs: Dict[str, Any] = {}
    defs.update(schema.get("$defs") or {})
    defs.update(schema.get("definitions") or {})
    return _inline(schema, defs, frozenset())


def _inline(node: Any, defs: Dict[str, Any], visited: frozenset) -> Any:
    """递归内联节点中的 $ref。

    Args:
        node: 当前处理的节点
        defs: 由顶层 ``$defs`` / ``definitions`` 合并得到的引用字典
        visited: 当前 $ref 解析路径上已出现过的引用名集合，用于防止循环引用
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = _resolve_ref(ref, defs)
            ref_key = ref.lstrip("#").lstrip("/").split("/")[-1]
            if target is not None and ref_key not in visited:
                # 内联目标：先把目标复制一份递归处理（带上当前 visited + 本引用名）
                inlined = _inline(dict(target), defs, visited | {ref_key})
                # $ref 节点上的非 $ref 键视为对引用的覆盖/扩展，合并进去（覆盖优先）
                for k, v in node.items():
                    if k == "$ref":
                        continue
                    inlined[k] = _inline(v, defs, visited)
                inlined.pop("$defs", None)
                inlined.pop("definitions", None)
                return inlined
            # target 不可解析或循环引用：保留 $ref（不强行删除，避免破坏语义）
        result = {}
        for key, value in node.items():
            if key in ("$defs", "definitions", "additionalProperties"):
                continue
            result[key] = _inline(value, defs, visited)
        return result
    if isinstance(node, list):
        return [_inline(item, defs, visited) for item in node]
    return node


def _resolve_ref(ref: str, defs: Dict[str, Any]) -> Any:
    """解析本地 $ref 字符串到 defs 中对应的目标节点。

    支持形如 ``#/$defs/Foo``、``#/definitions/Foo`` 的本地引用；
    对 defs 中不存在或非本地引用，返回 None。
    """
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    path = ref[1:].lstrip("/")
    if not path:
        return None
    parts = path.split("/")
    # 引用形如 #/$defs/Foo 或 #/definitions/Foo 时，前缀段是 $defs/definitions，
    # 直接从扁平 defs 字典里取，跳过该前缀段。
    if parts and parts[0] in ("$defs", "definitions"):
        parts = parts[1:]
    cur: Any = defs
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur
