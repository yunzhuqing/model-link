from fastapi import FastAPI
from . import models, database
from .routers import users, providers, gateway, apikeys
from fastapi.middleware.cors import CORSMiddleware

# 创建数据库表
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title="AI Gateway API",
    description="""
    AI Gateway - Unified interface for multiple LLM providers.
    
    ## Features
    - OpenAI-compatible API endpoints
    - Anthropic-compatible API endpoints
    - Multiple provider support (OpenAI, Anthropic, DeepSeek, Moonshot, Zhipu, Ollama, vLLM)
    - Provider and model management
    - User authentication
    
    ## Usage
    1. Register a user account
    2. Login to get an access token
    3. Configure your providers and models
    4. Use the /v1/chat/completions endpoint for OpenAI-compatible requests
    5. Use the /v1/messages endpoint for Anthropic-compatible requests
    """,
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(users.router, tags=["users"])
app.include_router(providers.router, prefix="/api", tags=["providers"])
app.include_router(gateway.router, tags=["gateway"])
app.include_router(apikeys.router, prefix="/api", tags=["api-keys"])

@app.get("/")
def read_root():
    return {
        "message": "Welcome to AI Gateway API",
        "docs": "/docs",
        "endpoints": {
            "openai_compatible": "/v1/chat/completions",
            "anthropic_compatible": "/v1/messages",
            "models": "/v1/models",
            "providers": "/api/providers/",
            "register": "/register",
            "login": "/token"
        }
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}
