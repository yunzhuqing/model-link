"""
Model Context Protocol (MCP) 模块。

提供一个独立的 MCP server，暴露查询火山引擎 Seedance 内容封控原因
(GetModerationResult) 的工具，供 Claude Desktop / IDE 等 MCP 客户端调用。

入口：``python -m app.mcp.server``（stdio transport）。
"""
