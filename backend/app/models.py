"""
Database models for Flask-SQLAlchemy.
"""
from datetime import datetime
from app import db
import hashlib


class BackgroundResponse(db.Model):
    """
    Stores the state of async background responses for /v1/responses?background=true.

    When a client sends a request with background=true, the gateway immediately returns
    a response_id and processes the actual LLM call asynchronously in a background thread.
    The client can later poll /v1/responses/{response_id} to retrieve the completed result.

    The actual request payload and output are NOT stored in the database — they are written
    to files (or object storage).  input_key and output_key hold the paths to those files.

    Fields:
        id          - Auto-increment BigInteger primary key.
        response_id - Unique response identifier (e.g. "resp_xxxx"), returned to the client.
        apikey      - The API key used to make the original request (for auth on retrieval).
        status      - Current state: "queued" | "in_progress" | "completed" | "failed".
        input_key   - File path where the JSON request payload is stored.
        output_key  - File path where the JSON formatted response is stored (when completed).
        error       - Error message when status="failed".
        model       - Model name used in the request.
        created_at  - Timestamp when the background job was created.
        completed_at- Timestamp when the job finished (completed or failed).
    """
    __tablename__ = "ml_background_responses"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    response_id = db.Column(db.String(100), unique=True, nullable=False, index=True)  # resp_xxx
    apikey = db.Column(db.String(200), nullable=True)         # API key used for the request
    status = db.Column(db.String(20), default="in_progress")  # queued / in_progress / completed / failed
    input_key = db.Column(db.String(500), nullable=True)      # File path for request payload
    output_key = db.Column(db.String(500), nullable=True)     # File path for output response
    error = db.Column(db.Text, nullable=True)                 # Error message if failed
    model = db.Column(db.String(100), nullable=True)          # Model name from the request
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.response_id,
            "status": self.status,
            "input_key": self.input_key,
            "output_key": self.output_key,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


# User-Group association table (many-to-many) with roles
class UserGroup(db.Model):
    """Association table for User-Group with role support"""
    __tablename__ = 'ml_user_groups'
    
    user_id = db.Column(db.Integer, db.ForeignKey('ml_users.id'), primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('ml_groups.id'), primary_key=True)
    role = db.Column(db.String(20), default='member')  # root, admin, member
    
    user = db.relationship("User", back_populates="group_associations")
    group = db.relationship("Group", back_populates="user_associations")


class User(db.Model):
    __tablename__ = "ml_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    hashed_password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, index=True)
    
    # User's groups through association
    group_associations = db.relationship("UserGroup", back_populates="user", cascade="all, delete-orphan")
    groups = db.relationship("Group", secondary="ml_user_groups", back_populates="users", viewonly=True)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email
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
    
    # Users in group through association
    user_associations = db.relationship("UserGroup", back_populates="group", cascade="all, delete-orphan")
    users = db.relationship("User", secondary="ml_user_groups", back_populates="groups", viewonly=True)
    # API Keys in group (one-to-many)
    api_keys = db.relationship("ApiKey", back_populates="group", cascade="all, delete-orphan")
    # Providers in group (one-to-many)
    providers = db.relationship("Provider", back_populates="group", cascade="all, delete-orphan")

    def to_dict(self):
        # Include role information with users
        user_list = []
        for ug in self.user_associations:
            user_list.append({
                'id': ug.user.id,
                'username': ug.user.username,
                'email': ug.user.email,
                'role': ug.role
            })
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'users': user_list,
            'api_keys': [k.to_dict_simple() for k in self.api_keys],
            'providers': [p.to_dict_simple() for p in self.providers]
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
    user_id = db.Column(db.Integer, db.ForeignKey("ml_users.id"), nullable=True, index=True)
    
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
    user = db.relationship("User", backref="api_keys")

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'group_id': self.group_id,
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
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
            'is_active': self.is_active,
            'user_name': self.user.username if self.user else None,
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
    api_key = db.Column(db.Text)
    base_url = db.Column(db.String(500))
    group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id"), nullable=False)
    authorization = db.Column(db.String(50), nullable=True, default="Authorization")  # "Authorization" for Bearer token, "custom" for custom header (e.g., x-goog-api-key)
    extra_config = db.Column(db.JSON, nullable=True)  # Provider-specific extra config (e.g. api_version for Azure)
    tags = db.Column(db.JSON, nullable=True)  # Tags for billing usage binding (e.g. ["production", "team-a"])

    models = db.relationship("Model", back_populates="provider", cascade="all, delete-orphan")
    group = db.relationship("Group", back_populates="providers")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'api_key': '***' if self.api_key else None,  # Don't expose API key
            'base_url': self.base_url,
            'group_id': self.group_id,
            'authorization': self.authorization or 'Authorization',
            'extra_config': self.extra_config or {},
            'tags': self.tags or [],
            'models': [m.to_dict() for m in self.models]
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'base_url': self.base_url,
            'group_id': self.group_id,
            'authorization': self.authorization or 'Authorization',
            'extra_config': self.extra_config or {},
            'tags': self.tags or []
        }


class ModelTemplate(db.Model):
    """Pre-defined model templates that users can select to auto-fill the Add Model form."""
    __tablename__ = "ml_model_templates"

    id = db.Column(db.Integer, primary_key=True, index=True)
    label = db.Column(db.String(100), nullable=False)         # Display name in the UI
    provider = db.Column(db.String(50), nullable=False)       # Provider group (OpenAI, Anthropic, …)
    name = db.Column(db.String(100), nullable=False)          # Actual model ID sent to the API
    alias = db.Column(db.String(100), nullable=True)          # Suggested alias

    # Size
    context_size = db.Column(db.Integer, default=4096)
    input_size = db.Column(db.Integer, default=4096)
    output_size = db.Column(db.Integer, default=4096)  # Maximum output tokens

    # Reasoning effort default (none / low / medium / high)
    reasoning_effort = db.Column(db.String(20), nullable=True, default=None)

    # Comma-separated list of accepted image formats, e.g. "png,jpeg,webp"
    # Empty / NULL means no restriction (all common formats accepted)
    supported_image_formats = db.Column(db.Text, nullable=True, default=None)

    # Optional tiered pricing — list of dicts:
    # [{"label": "<=272k", "context_size": 272000, "input_size": 272000, "output_size": 8192,
    #   "input_price": 2.5, "output_price": 15, "cache_creation_price": 0, "cache_hit_price": 0.25}]
    # When present, users pick a tier in the UI; the tier overrides the base price/size fields.
    pricing_tiers = db.Column(db.JSON, nullable=True, default=None)

    # Pricing ($ per 1M tokens)  — these are the default / first-tier values
    input_price = db.Column(db.Float, default=0.0)
    output_price = db.Column(db.Float, default=0.0)
    cache_creation_price = db.Column(db.Float, default=0.0)
    cache_hit_price = db.Column(db.Float, default=0.0)

    # Currency for pricing (e.g. "USD", "CNY")
    currency = db.Column(db.String(10), nullable=True, default='USD')

    # Retirement time — after this datetime the template is considered obsolete
    retirement_time = db.Column(db.DateTime, nullable=True, default=None)

    # Rate limits
    rpm = db.Column(db.Integer, nullable=True, default=None)   # requests per minute (None = unlimited)
    tpm = db.Column(db.Integer, nullable=True, default=None)   # tokens per minute (None = unlimited)

    # Discount multiplier (e.g. 0.9 = 10% off; 1.0 = no discount)
    discount = db.Column(db.Float, nullable=True, default=1.0)

    # Feature flags
    support_kvcache = db.Column(db.Boolean, default=False)
    support_image = db.Column(db.Boolean, default=False)
    support_audio = db.Column(db.Boolean, default=False)
    support_video = db.Column(db.Boolean, default=False)
    support_file = db.Column(db.Boolean, default=False)
    support_web_search = db.Column(db.Boolean, default=False)
    support_tool_search = db.Column(db.Boolean, default=False)
    support_thinking = db.Column(db.Boolean, default=False)
    support_online_image = db.Column(db.Boolean, default=False)
    support_online_video = db.Column(db.Boolean, default=False)
    support_embedding = db.Column(db.Boolean, default=False)

    @property
    def is_retired(self):
        """Returns True if the template has passed its retirement time."""
        if self.retirement_time is None:
            return False
        return datetime.utcnow() >= self.retirement_time

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'provider': self.provider,
            'name': self.name,
            'alias': self.alias,
            'context_size': self.context_size,
            'input_size': self.input_size,
            'output_size': self.output_size,
            'reasoning_effort': self.reasoning_effort,
            'supported_image_formats': self.supported_image_formats,
            'pricing_tiers': self.pricing_tiers,
            'input_price': self.input_price,
            'output_price': self.output_price,
            'cache_creation_price': self.cache_creation_price,
            'cache_hit_price': self.cache_hit_price,
            'currency': self.currency or 'USD',
            'retirement_time': self.retirement_time.isoformat() if self.retirement_time else None,
            'is_retired': self.is_retired,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'discount': self.discount if self.discount is not None else 1.0,
            'support_kvcache': self.support_kvcache,
            'support_image': self.support_image,
            'support_audio': self.support_audio,
            'support_video': self.support_video,
            'support_file': self.support_file,
            'support_web_search': self.support_web_search,
            'support_tool_search': self.support_tool_search,
            'support_thinking': self.support_thinking,
            'support_online_image': self.support_online_image,
            'support_online_video': self.support_online_video,
            'support_embedding': self.support_embedding,
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
    output_size = db.Column(db.Integer, default=4096)  # Maximum output tokens
    input_price = db.Column(db.Float, default=0.0)
    output_price = db.Column(db.Float, default=0.0)

    # Reasoning effort default (none / low / medium / high)
    reasoning_effort = db.Column(db.String(20), nullable=True, default=None)

    # Comma-separated list of accepted image formats, e.g. "png,jpeg,webp"
    # Empty / NULL means no restriction (all common formats accepted)
    supported_image_formats = db.Column(db.Text, nullable=True, default=None)

    # Optional tiered pricing — same structure as ModelTemplate.pricing_tiers
    # [{"label": "<=272k", "context_size": 272000, "input_size": 272000, "output_size": 8192,
    #   "input_price": 2.5, "output_price": 15, "cache_creation_price": 0, "cache_hit_price": 0.25}]
    pricing_tiers = db.Column(db.JSON, nullable=True, default=None)

    # Cache pricing
    cache_creation_price = db.Column(db.Float, default=0.0)
    cache_hit_price = db.Column(db.Float, default=0.0)

    # Currency for pricing (e.g. "USD", "CNY")
    currency = db.Column(db.String(10), nullable=True, default='USD')

    # Retirement time — after this datetime the model is considered retired and cannot be used
    retirement_time = db.Column(db.DateTime, nullable=True, default=None)

    # Rate limits
    rpm = db.Column(db.Integer, nullable=True, default=None)   # requests per minute (None = unlimited)
    tpm = db.Column(db.Integer, nullable=True, default=None)   # tokens per minute (None = unlimited)

    # Discount multiplier (e.g. 0.9 = 10% off; 1.0 = no discount)
    discount = db.Column(db.Float, nullable=True, default=1.0)

    # Feature support
    support_kvcache = db.Column(db.Boolean, default=False)
    support_image = db.Column(db.Boolean, default=False)
    support_audio = db.Column(db.Boolean, default=False)
    support_video = db.Column(db.Boolean, default=False)
    support_file = db.Column(db.Boolean, default=False)
    support_web_search = db.Column(db.Boolean, default=False)
    support_tool_search = db.Column(db.Boolean, default=False)
    support_thinking = db.Column(db.Boolean, default=False)
    support_online_image = db.Column(db.Boolean, default=True)  # Whether the provider supports image URLs directly; if False, URLs are converted to base64
    support_online_video = db.Column(db.Boolean, default=True)  # Whether the provider supports video URLs directly; if False, URLs are converted to base64
    support_embedding = db.Column(db.Boolean, default=False)  # Whether this is an embedding model

    provider = db.relationship("Provider", back_populates="models")

    @property
    def is_retired(self):
        """Returns True if the model has passed its retirement time."""
        if self.retirement_time is None:
            return False
        return datetime.utcnow() >= self.retirement_time

    def to_dict(self):
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'name': self.name,
            'alias': self.alias,
            'context_size': self.context_size,
            'input_size': self.input_size,
            'output_size': self.output_size,
            'reasoning_effort': self.reasoning_effort,
            'supported_image_formats': self.supported_image_formats,
            'pricing_tiers': self.pricing_tiers,
            'input_price': self.input_price,
            'output_price': self.output_price,
            'cache_creation_price': self.cache_creation_price,
            'cache_hit_price': self.cache_hit_price,
            'currency': self.currency or 'USD',
            'retirement_time': self.retirement_time.isoformat() if self.retirement_time else None,
            'is_retired': self.is_retired,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'discount': self.discount if self.discount is not None else 1.0,
            'support_kvcache': self.support_kvcache,
            'support_image': self.support_image,
            'support_audio': self.support_audio,
            'support_video': self.support_video,
            'support_file': self.support_file,
            'support_web_search': self.support_web_search,
            'support_tool_search': self.support_tool_search,
            'support_thinking': self.support_thinking,
            'support_online_image': self.support_online_image,
            'support_online_video': self.support_online_video,
            'support_embedding': self.support_embedding
        }


class UsageRecord(db.Model):
    """
    Records the token consumption details for each API request.

    This table captures detailed billing information for every request
    processed by the gateway, including user identity, API key, model,
    provider, and all token/resource usage metrics.
    """
    __tablename__ = "ml_usage_records"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    # ── Identity ────────────────────────────────────────────────────────────
    # Human-readable user name (from JWT); null for API-key-only requests
    user_name = db.Column(db.String(100), nullable=True, index=True)

    # Group info (from API key's group)
    group_id = db.Column(db.Integer, nullable=True, index=True)
    group_name = db.Column(db.String(100), nullable=True, index=True)

    # API Key (SHA-256 hashed for privacy; first 8 chars stored for display)
    api_key_hash = db.Column(db.String(64), nullable=True, index=True)   # SHA-256 hex
    api_key_preview = db.Column(db.String(20), nullable=True)            # e.g. "sk-abc...xyz"
    api_key_name = db.Column(db.String(100), nullable=True)

    # ── Model / Provider ───────────────────────────────────────────────────
    model_name = db.Column(db.String(200), nullable=True, index=True)
    provider_id = db.Column(db.Integer, nullable=True, index=True)
    provider_name = db.Column(db.String(100), nullable=True, index=True)

    # ── Text token usage ───────────────────────────────────────────────────
    input_tokens = db.Column(db.BigInteger, default=0)
    input_price_unit = db.Column(db.Float, default=0.0)   # $ per 1M tokens

    output_tokens = db.Column(db.BigInteger, default=0)
    output_price_unit = db.Column(db.Float, default=0.0)  # $ per 1M tokens

    # Cache creation (Anthropic prompt caching write)
    cache_creation_tokens = db.Column(db.BigInteger, default=0)
    cache_creation_price_unit = db.Column(db.Float, default=0.0)

    # Cache hit (Anthropic prompt caching read / OpenAI cached_tokens)
    cache_tokens = db.Column(db.BigInteger, default=0)
    cache_token_price_unit = db.Column(db.Float, default=0.0)

    # Reasoning / thinking tokens (inside output)
    reasoning_tokens = db.Column(db.BigInteger, default=0)

    # ── Image output ───────────────────────────────────────────────────────
    output_image_number = db.Column(db.Integer, default=0)
    output_image_tokens = db.Column(db.BigInteger, default=0)
    output_image_resolution = db.Column(db.String(50), nullable=True)  # e.g. "1024x1024"
    output_image_aspect = db.Column(db.String(20), nullable=True)      # e.g. "1:1"
    output_image_price_unit = db.Column(db.Float, default=0.0)        # $ per image

    # ── Video output ───────────────────────────────────────────────────────
    output_video_number = db.Column(db.Integer, default=0)
    output_video_tokens = db.Column(db.BigInteger, default=0)
    output_video_resolution = db.Column(db.String(50), nullable=True)
    output_video_aspect = db.Column(db.String(20), nullable=True)
    output_video_seconds = db.Column(db.Float, default=0.0)
    output_video_price_unit = db.Column(db.Float, default=0.0)

    # ── Audio output ───────────────────────────────────────────────────────
    output_audio_tokens = db.Column(db.BigInteger, default=0)
    output_audio_seconds = db.Column(db.Float, default=0.0)
    output_audio_price_unit = db.Column(db.Float, default=0.0)

    # ── Web search ─────────────────────────────────────────────────────────
    web_search_requests = db.Column(db.Integer, default=0)
    web_search_price_unit = db.Column(db.Float, default=0.0)  # $ per search request

    # ── Currency / exchange rate ────────────────────────────────────────────
    # Pricing currency of the model (e.g. "USD", "CNY"). Copied from Model.currency.
    currency = db.Column(db.String(10), nullable=True, default='USD')
    # USD→CNY exchange rate at the time of the request.
    # When currency is already CNY this is 1.0.
    # cost_cny ≈ native_cost * exchange_rate_to_cny
    exchange_rate_to_cny = db.Column(db.Float, nullable=True, default=None)

    # ── Timestamp ──────────────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @staticmethod
    def _mask_key(raw_key: str) -> str:
        """Return a masked preview: first 5 + last 4 chars, middle replaced by '...'"""
        if not raw_key or len(raw_key) <= 9:
            return raw_key or ''
        return raw_key[:5] + '...' + raw_key[-4:]

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def to_dict(self):
        return {
            'id': self.id,
            'user_name': self.user_name,
            'group_id': self.group_id,
            'group_name': self.group_name,
            'api_key_hash': self.api_key_hash,
            'api_key_preview': self.api_key_preview,
            'api_key_name': self.api_key_name,
            'model_name': self.model_name,
            'provider_id': self.provider_id,
            'provider_name': self.provider_name,
            # Text tokens
            'input_tokens': self.input_tokens,
            'input_price_unit': self.input_price_unit,
            'output_tokens': self.output_tokens,
            'output_price_unit': self.output_price_unit,
            'cache_creation_tokens': self.cache_creation_tokens,
            'cache_creation_price_unit': self.cache_creation_price_unit,
            'cache_tokens': self.cache_tokens,
            'cache_token_price_unit': self.cache_token_price_unit,
            'reasoning_tokens': self.reasoning_tokens,
            # Image
            'output_image_number': self.output_image_number,
            'output_image_tokens': self.output_image_tokens,
            'output_image_resolution': self.output_image_resolution,
            'output_image_aspect': self.output_image_aspect,
            'output_image_price_unit': self.output_image_price_unit,
            # Video
            'output_video_number': self.output_video_number,
            'output_video_tokens': self.output_video_tokens,
            'output_video_resolution': self.output_video_resolution,
            'output_video_aspect': self.output_video_aspect,
            'output_video_seconds': self.output_video_seconds,
            'output_video_price_unit': self.output_video_price_unit,
            # Audio
            'output_audio_tokens': self.output_audio_tokens,
            'output_audio_seconds': self.output_audio_seconds,
            'output_audio_price_unit': self.output_audio_price_unit,
            # Web search
            'web_search_requests': self.web_search_requests,
            'web_search_price_unit': self.web_search_price_unit,
            # Timestamp
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
