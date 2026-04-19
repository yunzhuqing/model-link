---
name: model-link-ref
description: model-link project doc for reference
---

# My Skill

Model-Link is a ai gateway that supports various ai models and provides unified api for developers(/v1/chat/completions, /v1/responses, /v1/messages). It also supports tool calling, image and document input, and streaming response.

## Architecture
Model-Link has a modular architecture, which consists of the following components:
- **API Layer**: The entry point for all client requests, implemented using FastAPI. It handles routing, request validation, and response formatting.
- **adapter Layer**: Contains the logic for adapting requests and responses between the API layer and the provider implementations. This layer is responsible for translating the unified API format into the specific format required by each provider, and vice versa.
- **Provider Layer**: Contains implementations for various AI providers (e.g., OpenAI, Anthropic, etc.). Each provider implementation adheres to a common interface defined in the service layer, allowing for easy integration of new providers in the future.
- **Database Layer**: Manages data persistence using SQLAlchemy. It defines models for users, providers, tools, and other entities, and handles all database interactions.


## project structure
```
backend
|-- app
    |-- main.py              # FastAPI 应用入口
    |-- database.py          # 数据库配置
    |-- models.py            # SQLAlchemy 模型
    |-- schemas.py           # Pydantic 模式
    |-- auth.py              # 认证工具
    |-- abstraction/         # 中间抽象层
    |   |-- messages.py      # 消息抽象
    |   |-- tools.py         # 工具抽象
    |   |-- chat.py          # 对话抽象
    |   |-- streaming.py     # 流式响应抽象
    |-- providers/           # 供应商实现层
        |-- base.py          # 基础供应商接口
        |-- openai_provider.py
        |-- anthropic_provider.py
        |-- openai_compatible.py
    |-- routers/
        |-- users.py         # 用户相关路由
        |-- providers.py     # 供应商和模型路由
        |-- gateway.py       # AI Gateway 路由
    |-- adapter/             # 适配器层
        |-- __init__.py
        |-- messages_adapter.py  # 消息适配器
        |-- tools_adapter.py     # 工具适配器
        |-- chat_adapter.py      # 对话适配器
        |-- streaming_adapter.py # 流式响应适配器
    |-- data/                # 数据文件
        |-- *_templates.py  # 预定义的模型和工具模板
frontend
|-- src
    |-- components/          # React 组件
    |-- pages/               # 页面组件
    |-- services/            # API 服务
    |-- App.js               # React 应用入口
```



## Steps
