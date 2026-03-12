"""
Database models for Flask-SQLAlchemy.
"""
from datetime import datetime
from app import db


# User-Group association table (many-to-many)
user_group = db.Table(
    'ml_user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('ml_users.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('ml_groups.id'), primary_key=True)
)


class User(db.Model):
    __tablename__ = "ml_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    hashed_password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, index=True)
    
    # User's groups (many-to-many)
    groups = db.relationship("Group", secondary=user_group, back_populates="users")

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'groups': [g.to_dict_simple() for g in self.groups]
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email
        }


class Group(db.Model):
    """Group model - for managing API Key access permissions"""
    __tablename__ = "ml_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Users in group (many-to-many)
    users = db.relationship("User", secondary=user_group, back_populates="groups")
    # API Keys in group (one-to-many)
    api_keys = db.relationship("ApiKey", back_populates="group", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'users': [u.to_dict_simple() for u in self.users],
            'api_keys': [k.to_dict_simple() for k in self.api_keys]
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ApiKey(db.Model):
    """API Key model - for API access authentication"""
    __tablename__ = "ml_api_keys"

    id = db.Column(db.Integer, primary_key=True, index=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id"), nullable=False)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    
    # Usage stats
    request_count = db.Column(db.Integer, default=0)
    token_count = db.Column(db.Integer, default=0)
    
    # Relationships
    group = db.relationship("Group", back_populates="api_keys")

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'group_id': self.group_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'request_count': self.request_count,
            'token_count': self.token_count
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'name': self.name,
            'is_active': self.is_active
        }

    def to_dict_with_group(self):
        result = self.to_dict()
        result['group'] = self.group.to_dict_simple() if self.group else None
        return result


class Provider(db.Model):
    __tablename__ = "ml_providers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False, default="openai")  # openai, anthropic, deepseek, kimi, glm, minimax, bailian, volcengine, tencent
    description = db.Column(db.String(255))
    api_key = db.Column(db.String(255))
    base_url = db.Column(db.String(255))

    models = db.relationship("Model", back_populates="provider", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'api_key': '***' if self.api_key else None,  # Don't expose API key
            'base_url': self.base_url,
            'models': [m.to_dict() for m in self.models]
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'base_url': self.base_url
        }


class Model(db.Model):
    __tablename__ = "ml_models"

    id = db.Column(db.Integer, primary_key=True, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("ml_providers.id"))
    name = db.Column(db.String(100), nullable=False, index=True)
    alias = db.Column(db.String(100), nullable=True, index=True)  # Alias name for API access
    
    # Basic properties
    context_size = db.Column(db.Integer, default=4096)
    input_size = db.Column(db.Integer, default=4096)
    input_price = db.Column(db.Float, default=0.0)
    output_price = db.Column(db.Float, default=0.0)
    
    # Cache pricing
    cache_creation_price = db.Column(db.Float, default=0.0)
    cache_hit_price = db.Column(db.Float, default=0.0)
    
    # Feature support
    support_kvcache = db.Column(db.Boolean, default=False)
    support_image = db.Column(db.Boolean, default=False)
    support_audio = db.Column(db.Boolean, default=False)
    support_video = db.Column(db.Boolean, default=False)
    support_file = db.Column(db.Boolean, default=False)
    support_web_search = db.Column(db.Boolean, default=False)
    support_tool_search = db.Column(db.Boolean, default=False)

    provider = db.relationship("Provider", back_populates="models")

    def to_dict(self):
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'name': self.name,
            'alias': self.alias,
            'context_size': self.context_size,
            'input_size': self.input_size,
            'input_price': self.input_price,
            'output_price': self.output_price,
            'cache_creation_price': self.cache_creation_price,
            'cache_hit_price': self.cache_hit_price,
            'support_kvcache': self.support_kvcache,
            'support_image': self.support_image,
            'support_audio': self.support_audio,
            'support_video': self.support_video,
            'support_file': self.support_file,
            'support_web_search': self.support_web_search,
            'support_tool_search': self.support_tool_search
        }