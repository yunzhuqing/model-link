from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

# 用户-分组关联表 (多对多)
user_group = Table(
    'ml_user_groups',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('ml_users.id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('ml_groups.id'), primary_key=True)
)


class User(Base):
    __tablename__ = "ml_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, index=True)
    
    # 用户所属的分组 (多对多)
    groups = relationship("Group", secondary=user_group, back_populates="users")


class Group(Base):
    """分组模型 - 用于管理API Key的访问权限"""
    __tablename__ = "ml_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 分组中的用户 (多对多)
    users = relationship("User", secondary=user_group, back_populates="groups")
    # 分组下的API Keys (一对多)
    api_keys = relationship("ApiKey", back_populates="group", cascade="all, delete-orphan")


class ApiKey(Base):
    """API Key模型 - 用于API访问认证"""
    __tablename__ = "ml_api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)  # API Key
    name = Column(String(100), nullable=False)  # Key的名称/备注
    group_id = Column(Integer, ForeignKey("ml_groups.id"), nullable=False)  # 所属分组
    
    # 状态
    is_active = Column(Boolean, default=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # 过期时间 (可选)
    last_used_at = Column(DateTime, nullable=True)  # 最后使用时间
    
    # 使用统计
    request_count = Column(Integer, default=0)  # 请求次数
    token_count = Column(Integer, default=0)  # Token使用量
    
    # 关系
    group = relationship("Group", back_populates="api_keys")


class Provider(Base):
    __tablename__ = "ml_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(String(255))
    api_key = Column(String(255))
    base_url = Column(String(255))

    models = relationship("Model", back_populates="provider", cascade="all, delete-orphan")


class Model(Base):
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("ml_providers.id"))
    name = Column(String(100), index=True, nullable=False)
    
    # 基础属性
    context_size = Column(Integer, default=4096)
    input_size = Column(Integer, default=4096)
    input_price = Column(Float, default=0.0)
    output_price = Column(Float, default=0.0)
    
    # 缓存价格
    cache_creation_price = Column(Float, default=0.0)
    cache_hit_price = Column(Float, default=0.0)
    
    # 功能支持
    support_kvcache = Column(Boolean, default=False)
    support_image = Column(Boolean, default=False)
    support_audio = Column(Boolean, default=False)
    support_video = Column(Boolean, default=False)
    support_file = Column(Boolean, default=False)
    support_web_search = Column(Boolean, default=False)
    support_tool_search = Column(Boolean, default=False)

    provider = relationship("Provider", back_populates="models")