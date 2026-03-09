from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

# User Schemas
class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    groups: List["Group"] = []

    class Config:
        from_attributes = True

# Group Schemas
class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None

class GroupCreate(GroupBase):
    pass

class GroupUpdate(GroupBase):
    name: Optional[str] = None
    description: Optional[str] = None

class Group(GroupBase):
    id: int
    created_at: datetime
    users: List[User] = []
    api_keys: List["ApiKey"] = []

    class Config:
        from_attributes = True

# ApiKey Schemas
class ApiKeyBase(BaseModel):
    name: str
    group_id: int
    expires_at: Optional[datetime] = None

class ApiKeyCreate(ApiKeyBase):
    pass

class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None

class ApiKey(ApiKeyBase):
    id: int
    key: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    request_count: int = 0
    token_count: int = 0

    class Config:
        from_attributes = True

class ApiKeyWithGroup(ApiKey):
    group: Optional[Group] = None

# Model Schemas
class ModelBase(BaseModel):
    name: str
    context_size: int = 4096
    input_size: int = 4096
    input_price: float = 0.0
    output_price: float = 0.0
    cache_creation_price: float = 0.0
    cache_hit_price: float = 0.0
    support_kvcache: bool = False
    support_image: bool = False
    support_audio: bool = False
    support_video: bool = False
    support_file: bool = False
    support_web_search: bool = False
    support_tool_search: bool = False

class ModelCreate(ModelBase):
    provider_id: int

class ModelUpdate(ModelBase):
    name: Optional[str] = None

class Model(ModelBase):
    id: int
    provider_id: int

    class Config:
        from_attributes = True

# Provider Schemas
class ProviderBase(BaseModel):
    name: str
    description: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class ProviderCreate(ProviderBase):
    pass

class ProviderUpdate(ProviderBase):
    name: Optional[str] = None

class Provider(ProviderBase):
    id: int
    models: List[Model] = []

    class Config:
        from_attributes = True

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
