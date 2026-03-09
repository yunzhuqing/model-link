# AI Gateway - 模型链接管理系统

AI Gateway 是一个完整的 AI 网关管理系统，支持对接不同的模型供应商和自建模型。提供用户管理、供应商管理、模型管理以及统一的 API 兼容层。

## 架构设计

采用三层架构设计：

```
┌─────────────────────────────────────────────────────────────┐
│                    API 兼容层 (API Layer)                    │
│  ┌─────────────────────┐  ┌─────────────────────────────┐  │
│  │ OpenAI Compatible   │  │   Anthropic Compatible      │  │
│  │ /v1/chat/completions│  │   /v1/messages              │  │
│  └─────────────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   中间抽象层 (Abstraction Layer)             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Message  │ │  Tool    │ │  Chat    │ │  Streaming   │  │
│  │ 消息抽象 │ │ 工具抽象 │ │ 对话抽象 │ │   流式抽象   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                供应商实现层 (Provider Layer)                 │
│  ┌─────────┐ ┌───────────┐ ┌─────────┐ ┌────────────────┐ │
│  │ OpenAI  │ │ Anthropic │ │ DeepSeek│ │ OpenAI Compat  │ │
│  └─────────┘ └───────────┘ └─────────┘ ├────────────────┤ │
│  ┌─────────┐ ┌───────────┐ ┌─────────┐ │ Ollama/vLLM/.. │ │
│  │Moonshot │ │  Zhipu    │ │ Custom  │ │                │ │
│  └─────────┘ └───────────┘ └─────────┘ └────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 功能特性

### 用户管理
- 用户注册
- 用户登录 (JWT Token 认证)
- 用户删除

### 供应商管理
- 添加供应商
- 编辑供应商
- 删除供应商
- 支持的供应商类型：OpenAI, Anthropic, DeepSeek, Moonshot, Zhipu, Ollama, vLLM 及其他 OpenAI 兼容接口

### 模型管理
- 添加模型
- 编辑模型
- 删除模型
- 模型基础属性：
  - 名称
  - 上下文大小 (Context Size)
  - 输入大小 (Input Size)
  - 输入价格 (Input Price)
  - 输出价格 (Output Price)
  - 缓存创建价格 (Cache Creation Price)
  - 缓存命中价格 (Cache Hit Price)
- 模型功能支持：
  - KV Cache
  - 图片输入
  - 音频输入
  - 视频输入
  - 文件输入
  - Web Search
  - Tool Search

### AI Gateway API
- **OpenAI 兼容接口**: `/v1/chat/completions`
  - 支持 Chat Completions API
  - 支持流式响应 (SSE)
  - 支持工具调用 (Function Calling)
  - 支持多模态输入 (图片、音频等)
  
- **Anthropic 兼容接口**: `/v1/messages`
  - 支持 Messages API
  - 支持流式响应
  - 支持工具调用
  - 支持图片和 PDF 输入

## 技术栈

### 后端
- **Python 3.10+**
- **FastAPI** - 现代、高性能的 Web 框架
- **SQLAlchemy** - ORM
- **Pydantic** - 数据验证
- **httpx** - 异步 HTTP 客户端
- **JWT** - 身份认证
- **Passlib** - 密码哈希

### 前端
- **React 19** - UI 框架
- **TypeScript** - 类型安全
- **Tailwind CSS** - 样式框架
- **React Query** - 数据请求和缓存
- **React Router** - 路由管理
- **Axios** - HTTP 客户端
- **Lucide React** - 图标库

### 数据库
- 支持 **SQLite** (默认，开发使用)
- 支持 **MySQL** (生产环境)
- 支持 **PostgreSQL** (生产环境)
- 表名统一使用 `ml_` 前缀

## 项目结构

```
model-link/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 应用入口
│   │   ├── database.py          # 数据库配置
│   │   ├── models.py            # SQLAlchemy 模型
│   │   ├── schemas.py           # Pydantic 模式
│   │   ├── auth.py              # 认证工具
│   │   ├── abstraction/         # 中间抽象层
│   │   │   ├── __init__.py
│   │   │   ├── messages.py      # 消息抽象
│   │   │   ├── tools.py         # 工具抽象
│   │   │   ├── chat.py          # 对话抽象
│   │   │   └── streaming.py     # 流式响应抽象
│   │   ├── providers/           # 供应商实现层
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # 基础供应商接口
│   │   │   ├── openai_provider.py
│   │   │   ├── anthropic_provider.py
│   │   │   └── openai_compatible.py
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── users.py         # 用户相关路由
│   │       ├── providers.py     # 供应商和模型路由
│   │       └── gateway.py       # AI Gateway 路由
│   └── requirements.txt         # Python 依赖
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts        # Axios 客户端配置
│   │   ├── components/
│   │   │   └── Layout.tsx       # 页面布局组件
│   │   ├── contexts/
│   │   │   └── AuthContext.tsx  # 认证上下文
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # 仪表板
│   │   │   ├── LoginPage.tsx    # 登录页
│   │   │   ├── RegisterPage.tsx # 注册页
│   │   │   └── ProviderList.tsx # 供应商管理页
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## 快速开始

### 环境要求
- Python 3.10+
- Node.js 18+
- npm 或 yarn

### 后端设置

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Linux/macOS:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端设置

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 访问应用

- 前端: http://localhost:5173
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

## API 端点

### 用户相关
- `POST /register` - 用户注册
- `POST /token` - 用户登录 (获取 JWT Token)
- `DELETE /users/{user_id}` - 删除用户

### 供应商相关
- `GET /api/providers/` - 获取供应商列表
- `POST /api/providers/` - 创建供应商
- `PUT /api/providers/{id}` - 更新供应商
- `DELETE /api/providers/{id}` - 删除供应商

### 模型相关
- `POST /api/models/` - 创建模型
- `PUT /api/models/{id}` - 更新模型
- `DELETE /api/models/{id}` - 删除模型

### AI Gateway (OpenAI 兼容)
- `GET /v1/models` - 获取可用模型列表
- `POST /v1/chat/completions` - Chat Completions API
  - 支持流式响应 (stream: true)
  - 支持工具调用 (tools)
  - 支持多模态内容

### AI Gateway (Anthropic 兼容)
- `POST /v1/messages` - Anthropic Messages API
  - 支持流式响应
  - 支持工具调用
  - 支持图片和文档输入

## 使用示例

### OpenAI 兼容接口调用

```bash
# 非流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'

# 流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": true
  }'
```

### 工具调用示例

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "What is the weather in Beijing?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get the current weather for a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {
                "type": "string",
                "description": "City name"
              }
            },
            "required": ["location"]
          }
        }
      }
    ]
  }'
```

### Anthropic 兼容接口调用

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

## 数据库配置

### SQLite (默认)
默认使用 SQLite，无需额外配置，数据库文件会自动创建在 `backend/sql_app.db`。

### PostgreSQL
```bash
# 设置环境变量
export DATABASE_URL="postgresql://user:password@localhost/dbname"
```

### MySQL
```bash
# 设置环境变量
export DATABASE_URL="mysql+pymysql://user:password@localhost/dbname"
```

## 数据库表结构

### ml_users (用户表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| username | String(50) | 用户名，唯一 |
| email | String(100) | 邮箱，唯一 |
| hashed_password | String(255) | 密码哈希 |

### ml_providers (供应商表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| name | String(100) | 供应商名称，唯一 |
| description | String(255) | 描述 |
| api_key | String(255) | API Key |
| base_url | String(255) | API Base URL |

### ml_models (模型表)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| provider_id | Integer | 供应商 ID (外键) |
| name | String(100) | 模型名称 |
| context_size | Integer | 上下文大小 |
| input_size | Integer | 输入大小 |
| input_price | Float | 输入价格 ($/M tokens) |
| output_price | Float | 输出价格 ($/M tokens) |
| cache_creation_price | Float | 缓存创建价格 |
| cache_hit_price | Float | 缓存命中价格 |
| support_kvcache | Boolean | 支持 KV Cache |
| support_image | Boolean | 支持图片输入 |
| support_audio | Boolean | 支持音频输入 |
| support_video | Boolean | 支持视频输入 |
| support_file | Boolean | 支持文件输入 |
| support_web_search | Boolean | 支持 Web Search |
| support_tool_search | Boolean | 支持 Tool Search |

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| DATABASE_URL | 数据库连接字符串 | sqlite:///./sql_app.db |
| SECRET_KEY | JWT 密钥 | (内置密钥，生产环境请更换) |

## 支持的供应商

| 供应商 | 类型 | 特性支持 |
|--------|------|----------|
| OpenAI | 原生 | Chat, Streaming, Tools, Vision, Audio |
| Anthropic | 原生 | Chat, Streaming, Tools, Vision, PDF |
| DeepSeek | OpenAI 兼容 | Chat, Streaming, Tools, Caching |
| Moonshot | OpenAI 兼容 | Chat, Streaming, Tools, 长上下文 |
| Zhipu (GLM) | OpenAI 兼容 | Chat, Streaming, Tools, Vision |
| Ollama | OpenAI 兼容 | Chat, Streaming, 本地模型 |
| vLLM | OpenAI 兼容 | Chat, Streaming, 高性能推理 |
| 自定义 | OpenAI 兼容 | 自建模型服务 |

## 生产部署建议

1. **更换 SECRET_KEY**: 使用强随机字符串作为 JWT 密钥
2. **使用生产数据库**: 建议使用 PostgreSQL 或 MySQL
3. **启用 HTTPS**: 配置 SSL 证书
4. **反向代理**: 使用 Nginx 作为反向代理
5. **进程管理**: 使用 Gunicorn + Uvicorn 或 Supervisor

## License

MIT