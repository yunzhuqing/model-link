"""
Database models for Flask-SQLAlchemy (used with Quart via flask-sqlalchemy compatibility).
"""
from datetime import datetime
from decimal import Decimal
from app import db
from sqlalchemy import select, func, inspect as sa_inspect
from sqlalchemy.orm.attributes import NO_VALUE
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
    task_id = db.Column(db.String(200), nullable=True)        # Provider's external task ID for status sync
    provider_id = db.Column(db.Integer, nullable=True)        # Provider ID from ml_providers
    session_id = db.Column(db.String(100), nullable=True)     # Client session ID for tracer correlation
    request_id = db.Column(db.String(64), nullable=True)      # Original X-Request-Id
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


class Workspace(db.Model):
    """Workspace model — top-level tenant/space for global rate limiting."""
    __tablename__ = "ml_workspaces"

    id = db.Column(db.Integer, primary_key=True, index=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    api_keys = db.relationship("ApiKey", back_populates="workspace")
    rate_limits = db.relationship("WorkspaceRateLimit", back_populates="workspace", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_dict_simple(self):
        return self.to_dict()


class WorkspaceRateLimit(db.Model):
    """Workspace-level rate limit configuration for models, differentiated by provider type and account.

    Granularity levels:
      1. (workspace_id, model_name, provider_type, provider_id) — per-account limit
      2. (workspace_id, model_name, provider_type, provider_id=NULL) — shared limit for all accounts of a provider type
    """
    __tablename__ = "ml_workspace_rate_limits"

    id = db.Column(db.Integer, primary_key=True, index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("ml_workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name = db.Column(db.String(100), nullable=False, index=True)       # Model name / alias used as key
    provider_type = db.Column(db.String(50), nullable=False, index=True)     # Provider type (e.g. "openai", "deepseek", "anthropic")
    provider_id = db.Column(db.Integer, db.ForeignKey("ml_providers.id", ondelete="CASCADE"), nullable=True, index=True)  # NULL = shared for all accounts of this provider_type
    rpm = db.Column(db.BigInteger, nullable=True, default=None)                 # Requests per minute (null = unlimited)
    tpm = db.Column(db.BigInteger, nullable=True, default=None)                 # Tokens per minute (null = unlimited)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('workspace_id', 'model_name', 'provider_type', 'provider_id',
                            name='uq_workspace_model_provider_rate_limit'),
    )

    workspace = db.relationship("Workspace", back_populates="rate_limits")
    provider = db.relationship("Provider", foreign_keys=[provider_id])

    def to_dict(self):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'model_name': self.model_name,
            'provider_type': self.provider_type,
            'provider_id': self.provider_id,
            'provider_name': self.provider.name if self.provider else None,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class User(db.Model):
    """User model for authentication"""
    __tablename__ = "ml_users"
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    hashed_password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    
    # Users belong to groups through UserGroup association
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
    workspace_id = db.Column(db.Integer, db.ForeignKey("ml_workspaces.id"), nullable=True, index=True)
    monitoring_config = db.Column(db.JSON, nullable=True)
    tags = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = db.relationship("Workspace", backref="groups")
    # Users in group through association
    user_associations = db.relationship("UserGroup", back_populates="group", cascade="all, delete-orphan")
    users = db.relationship("User", secondary="ml_user_groups", back_populates="groups", viewonly=True)
    # API Keys in group (one-to-many)
    api_keys = db.relationship("ApiKey", back_populates="group", cascade="all, delete-orphan")
    # Providers in group (one-to-many)
    providers = db.relationship("Provider", back_populates="group", cascade="all, delete-orphan")
    # Models shared TO this group
    model_shares_incoming = db.relationship(
        "ModelShare", foreign_keys="ModelShare.target_group_id",
        back_populates="target_group", cascade="all, delete-orphan"
    )
    # Models shared FROM this group
    model_shares_outgoing = db.relationship(
        "ModelShare", foreign_keys="ModelShare.source_group_id",
        back_populates="source_group", cascade="all, delete-orphan"
    )

    @staticmethod
    def _sanitize_monitoring_config(mc):
        """Strip secret_key from monitoring config before returning to client."""
        if mc is None:
            return None
        items = [mc] if isinstance(mc, dict) else mc
        result = []
        for item in items:
            item = dict(item)
            item.pop('secret_key', None)
            result.append(item)
        return result

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
            'workspace_id': self.workspace_id,
            'monitoring_config': self._sanitize_monitoring_config(self.monitoring_config),
            'tags': self.tags or [],
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
            'workspace_id': self.workspace_id,
            'monitoring_config': self._sanitize_monitoring_config(self.monitoring_config),
            'tags': self.tags or [],
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ApiKey(db.Model):
    """API Key model - for API access authentication"""
    __tablename__ = "ml_api_keys"

    id = db.Column(db.Integer, primary_key=True, index=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("ml_users.id"), nullable=True, index=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    
    # Usage stats (updated periodically from cache by leader node)
    request_count = db.Column(db.BigInteger, default=0)
    token_count = db.Column(db.BigInteger, default=0)
    
    # Historical cumulative usage stats (synced from cache)
    total_input_tokens = db.Column(db.BigInteger, default=0)
    total_output_tokens = db.Column(db.BigInteger, default=0)
    total_reasoning_tokens = db.Column(db.BigInteger, default=0)
    total_cost_usd = db.Column(db.Float, default=0.0)        # Total cost in USD
    total_image_count = db.Column(db.BigInteger, default=0)      # Total images generated
    total_video_count = db.Column(db.BigInteger, default=0)      # Total videos generated
    total_audio_seconds = db.Column(db.Float, default=0.0)       # Total audio seconds generated
    total_web_search_requests = db.Column(db.BigInteger, default=0)  # Total web search requests
    total_credits = db.Column(db.Float, default=0.0)            # Total 3D generation credits

    # Incremental sync position — the max UsageRecord.id covered by the last sync cycle
    last_stat_id = db.Column(db.BigInteger, default=0, nullable=False)
    # Incremental compress position — the max UsageRecord.id covered by the last compress cycle
    last_compress_id = db.Column(db.BigInteger, default=0, nullable=False)
    # Snapshot of total remaining budget at the time of the last sync (sum of all budget records)
    last_synced_remaining = db.Column(db.Float, nullable=True, default=None)

    # Allowed models — JSON list of model names (e.g. ["gpt-4o", "claude-3.5-sonnet"])
    # NULL or empty list means all models are allowed.
    allowed_models = db.Column(db.JSON, nullable=True, default=None)

    # Tags — key-value pairs for categorization (e.g. [{"name": "dept", "value": "a"}])
    tags = db.Column(db.JSON, nullable=True)

    # Budget — remaining spending allowance for this API key (in USD).
    # When adding budget, it is appended to the current remaining amount.
    # NULL means no budget has been set yet (check unlimited_budget for behavior).
    budget = db.Column(db.Float, nullable=True, default=None)
    
    # Unlimited budget flag — if True, no budget deduction is performed.
    # The API key can spend without limit regardless of the budget field.
    unlimited_budget = db.Column(db.Boolean, default=False, nullable=False)

    # API-key-level rate limits (null = no limit)
    rpm = db.Column(db.BigInteger, nullable=True)
    tpm = db.Column(db.BigInteger, nullable=True)

    # Workspace
    workspace_id = db.Column(db.Integer, db.ForeignKey("ml_workspaces.id"), nullable=True, index=True)
    
    # Relationships
    group = db.relationship("Group", back_populates="api_keys")
    user = db.relationship("User", backref="api_keys")
    workspace = db.relationship("Workspace", back_populates="api_keys")
    budgets = db.relationship("ApiKeyBudget", back_populates="api_key", cascade="all, delete-orphan",
                              order_by="ApiKeyBudget.created_at")

    def to_dict(self):
        state = sa_inspect(self)
        return {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'description': self.description,
            'group_id': self.group_id,
            'user_id': self.user_id,
            'workspace_id': self.workspace_id,
            'user_name': self.user.username if state.attrs.user.loaded_value is not NO_VALUE and self.user else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'request_count': self.request_count,
            'token_count': self.token_count,
            'allowed_models': self.allowed_models or [],
            'tags': self.tags or [],
            'budget': self.budget,
            'unlimited_budget': self.unlimited_budget,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'policies': [p.to_dict() for p in self.policies] if state.attrs.policies.loaded_value is not NO_VALUE else [],
        }

    def to_dict_simple(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'user_name': self.user.username if self.user else None,
        }

    def to_dict_with_group(self):
        result = self.to_dict()
        result['group'] = self.group.to_dict_simple() if self.group else None
        return result


class Provider(db.Model):
    __tablename__ = "ml_providers"
    __table_args__ = (
        db.UniqueConstraint('name', 'group_id', name='uq_provider_name_group'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False, default="openai")  # openai, anthropic, deepseek, kimi, glm, minimax, bailian, volcengine, tencent
    description = db.Column(db.String(255))
    api_key = db.Column(db.Text)
    base_url = db.Column(db.String(500))
    group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id"), nullable=False)
    authorization = db.Column(db.String(50), nullable=True, default="Authorization")  # "Authorization" for Bearer token, "custom" for custom header (e.g., x-goog-api-key)
    extra_config = db.Column(db.JSON, nullable=True)  # Provider-specific extra config (e.g. api_version for Azure)
    tags = db.Column(db.JSON, nullable=True)  # Tags for billing usage binding (e.g. ["production", "team-a"])
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Whether this provider is enabled

    models = db.relationship("Model", back_populates="provider", cascade="all, delete-orphan")
    group = db.relationship("Group", back_populates="providers")

    @staticmethod
    def _mask_api_key(raw_key):
        """Return a masked preview: first 5 + '...' + last 4. Short keys are fully masked."""
        if not raw_key:
            return None
        if len(raw_key) <= 9:
            return '*' * len(raw_key)
        return raw_key[:5] + '...' + raw_key[-4:]

    def to_dict(self):
        state = sa_inspect(self)
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'api_key': self._mask_api_key(self.api_key),  # Masked preview; use /reveal-key for full value
            'base_url': self.base_url,
            'group_id': self.group_id,
            'authorization': self.authorization or 'Authorization',
            'extra_config': self.extra_config or {},
            'tags': self.tags or [],
            'is_active': self.is_active,
            'models': [m.to_dict() for m in self.models] if state.attrs.models.loaded_value is not NO_VALUE else [],
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
            'tags': self.tags or [],
            'is_active': self.is_active
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

    # Output pricing strategies for image / video / audio generation models.
    # Same schema as Model.output_pricing.
    output_pricing = db.Column(db.JSON, nullable=True, default=None)

    # Pricing ($ per 1M tokens)  — these are the default / first-tier values
    input_price = db.Column(db.Numeric(20, 10), default=0)
    output_price = db.Column(db.Numeric(20, 10), default=0)
    cache_creation_price = db.Column(db.Numeric(20, 10), default=0)
    cache_5m_creation_price = db.Column(db.Numeric(20, 10), default=0)  # 5-minute ephemeral cache creation price ($ per 1M tokens)
    cache_1h_creation_price = db.Column(db.Numeric(20, 10), default=0)  # 1-hour ephemeral cache creation price ($ per 1M tokens)
    cache_hit_price = db.Column(db.Numeric(20, 10), default=0)

    # Currency for pricing (e.g. "USD", "CNY")
    currency = db.Column(db.String(10), nullable=True, default='USD')

    # Retirement time — after this datetime the template is considered obsolete
    retirement_time = db.Column(db.DateTime, nullable=True, default=None)

    # Rate limits
    rpm = db.Column(db.BigInteger, nullable=True, default=None)   # requests per minute (None = unlimited)
    tpm = db.Column(db.BigInteger, nullable=True, default=None)   # tokens per minute (None = unlimited)

    # Discount multiplier (e.g. 0.9 = 10% off; 1.0 = no discount)
    discount = db.Column(db.Numeric(10, 4), nullable=True, default=1)

    # Request timeout in seconds (None = use system default 300s).
    # Different model types may need very different timeouts, e.g.
    # chat models ~60s, image generation ~600s, video ~1200s, 3D ~2400s.
    timeout = db.Column(db.Integer, nullable=True, default=None)

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

    # Supported API access types, comma-separated: chat_completions,responses,messages
    # NULL or empty means all types are supported (backward compatible)
    api_type = db.Column(db.String(100), nullable=True, default=None)

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
            'output_pricing': self.output_pricing,
            'input_price': self.input_price,
            'output_price': self.output_price,
            'cache_creation_price': self.cache_creation_price,
            'cache_5m_creation_price': self.cache_5m_creation_price,
            'cache_1h_creation_price': self.cache_1h_creation_price,
            'cache_hit_price': self.cache_hit_price,
            'currency': self.currency or 'USD',
            'retirement_time': self.retirement_time.isoformat() if self.retirement_time else None,
            'is_retired': self.is_retired,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'discount': self.discount if self.discount is not None else 1.0,
            'timeout': self.timeout,
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
            'api_type': self.api_type,
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
    input_price = db.Column(db.Numeric(20, 10), default=0)
    output_price = db.Column(db.Numeric(20, 10), default=0)

    # Reasoning effort default (none / low / medium / high)
    reasoning_effort = db.Column(db.String(20), nullable=True, default=None)

    # Comma-separated list of accepted image formats, e.g. "png,jpeg,webp"
    # Empty / NULL means no restriction (all common formats accepted)
    supported_image_formats = db.Column(db.Text, nullable=True, default=None)

    # Optional tiered pricing — same structure as ModelTemplate.pricing_tiers
    # [{"label": "<=272k", "context_size": 272000, "input_size": 272000, "output_size": 8192,
    #   "input_price": 2.5, "output_price": 15, "cache_creation_price": 0, "cache_hit_price": 0.25}]
    pricing_tiers = db.Column(db.JSON, nullable=True, default=None)

    # Output pricing strategies for image / video / audio generation models.
    # JSON structure:
    # {
    #   "image": {"type": "per_image"|"per_token", "price": <float>, "tiers": [{"resolution": "1K", "price": <float>}, ...]},
    #   "video": {"type": "per_second"|"per_token", "price": <float>, "tiers": [{"resolution": "720p", "audio": false, "price": <float>}, ...]},
    #   "audio": {"type": "per_second"|"per_token", "price": <float>}
    # }
    output_pricing = db.Column(db.JSON, nullable=True, default=None)

    # Cache pricing
    cache_creation_price = db.Column(db.Numeric(20, 10), default=0)  # Simple cache creation price ($ per 1M tokens)
    cache_5m_creation_price = db.Column(db.Numeric(20, 10), default=0)  # 5-minute ephemeral cache creation price ($ per 1M tokens)
    cache_1h_creation_price = db.Column(db.Numeric(20, 10), default=0)  # 1-hour ephemeral cache creation price ($ per 1M tokens)
    cache_hit_price = db.Column(db.Numeric(20, 10), default=0)

    # Currency for pricing (e.g. "USD", "CNY")
    currency = db.Column(db.String(10), nullable=True, default='USD')

    # Retirement time — after this datetime the model is considered retired and cannot be used
    retirement_time = db.Column(db.DateTime, nullable=True, default=None)

    # Rate limits
    rpm = db.Column(db.BigInteger, nullable=True, default=None)   # requests per minute (None = unlimited)
    tpm = db.Column(db.BigInteger, nullable=True, default=None)   # tokens per minute (None = unlimited)

    # Discount multiplier (e.g. 0.9 = 10% off; 1.0 = no discount)
    discount = db.Column(db.Numeric(10, 4), nullable=True, default=1)

    # Request timeout in seconds (None = use system default 300s).
    # Different model types may need very different timeouts, e.g.
    # chat models ~60s, image generation ~600s, video ~1200s, 3D ~2400s.
    timeout = db.Column(db.Integer, nullable=True, default=None)

    # Priority for multi-provider routing (higher = more preferred, default 0)
    priority = db.Column(db.Integer, default=0, nullable=False)
    # Traffic ratio (0-100) for load distribution among same-priority providers
    traffic_ratio = db.Column(db.Integer, default=0, nullable=False)

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
    is_active = db.Column(db.Boolean, default=True, nullable=False)  # Whether this model is enabled

    # Supported API access types, comma-separated: chat_completions,responses,messages
    # NULL or empty means all types are supported (backward compatible)
    api_type = db.Column(db.String(100), nullable=True, default=None)

    provider = db.relationship("Provider", back_populates="models")
    shares = db.relationship("ModelShare", back_populates="model", cascade="all, delete-orphan")

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
            'output_pricing': self.output_pricing,
            'input_price': self.input_price,
            'output_price': self.output_price,
            'cache_creation_price': self.cache_creation_price,
            'cache_5m_creation_price': self.cache_5m_creation_price,
            'cache_1h_creation_price': self.cache_1h_creation_price,
            'cache_hit_price': self.cache_hit_price,
            'currency': self.currency or 'USD',
            'retirement_time': self.retirement_time.isoformat() if self.retirement_time else None,
            'is_retired': self.is_retired,
            'rpm': self.rpm,
            'tpm': self.tpm,
            'discount': self.discount if self.discount is not None else 1.0,
            'timeout': self.timeout,
            'priority': self.priority,
            'traffic_ratio': self.traffic_ratio,
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
            'is_active': self.is_active,
            'api_type': self.api_type
        }


class ModelShare(db.Model):
    """Records models shared from one group to another."""
    __tablename__ = "ml_model_shares"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    model_id = db.Column(db.Integer, db.ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False)
    source_group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id", ondelete="CASCADE"), nullable=False)
    target_group_id = db.Column(db.Integer, db.ForeignKey("ml_groups.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("ml_users.id"), nullable=True)

    model = db.relationship("Model", back_populates="shares")
    source_group = db.relationship("Group", foreign_keys=[source_group_id], back_populates="model_shares_outgoing")
    target_group = db.relationship("Group", foreign_keys=[target_group_id], back_populates="model_shares_incoming")

    __table_args__ = (
        db.UniqueConstraint('model_id', 'target_group_id', name='uq_model_share_target'),
    )


class ApiKeyBudget(db.Model):
    """
    Budget records for API keys.

    Each API key can have multiple budget entries. Budgets are consumed in
    chronological order (oldest first). When a request costs money, the
    system deducts from the oldest budget with remaining > 0. If that budget
    is exhausted, it continues to the next one.

    The available quota for an API key is the sum of `remaining` across all
    its budget records.

    Fields:
        id          - Auto-increment primary key.
        api_key_id  - Foreign key to ml_api_keys.id.
        amount      - Original budget amount in USD.
        remaining   - Remaining budget in USD (decremented on each request).
        created_at  - When this budget entry was created.
        updated_at  - Last time this budget entry was modified.
    """
    __tablename__ = "ml_api_key_budgets"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey("ml_api_keys.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Numeric(20, 6), nullable=False, default=0)      # Original budget amount (USD)
    remaining = db.Column(db.Numeric(20, 6), nullable=False, default=0)   # Remaining budget (USD)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship back to ApiKey
    api_key = db.relationship("ApiKey", back_populates="budgets")

    def to_dict(self):
        return {
            'id': self.id,
            'api_key_id': self.api_key_id,
            'amount': round(float(self.amount), 6) if self.amount is not None else 0.0,
            'remaining': round(float(self.remaining), 6) if self.remaining is not None else 0.0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ApiKeyPolicy(db.Model):
    """Per-API-key policy/config table — extensible for multiple policy types.

    policy_type examples:
      - "compress"     → config: {"per_minute": 100, "per_hour": 1000}
      - "budget_alert" → config: {"threshold": 10.0, "channels": ["email"], ...}
    """
    __tablename__ = "ml_api_key_policies"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey("ml_api_keys.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_type = db.Column(db.String(50), nullable=False)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    config = db.Column(db.JSON, nullable=False, default={})
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_key = db.relationship("ApiKey", backref="policies")

    __table_args__ = (
        db.UniqueConstraint('api_key_id', 'policy_type', name='uq_api_key_policy_type'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'api_key_id': self.api_key_id,
            'policy_type': self.policy_type,
            'enabled': self.enabled,
            'config': self.config,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Permission(db.Model):
    """
    System-level permission model — global permission points apply to all groups.

    Root users can create, edit, delete, and toggle permission points.
    Each permission point defines which roles (root / admin / member) are
    allowed and whether the point is currently enabled.
    Permissions are system-global: they apply uniformly across all groups.

    Fields:
        key           - Globally unique permission key (e.g. "provider.manage").
        label         - Human-readable display name shown in the UI.
        description   - Optional longer description.
        allowed_roles - JSON list of roles that are permitted, e.g. ["root", "admin"].
        is_enabled    - Master toggle. When False the permission is denied to EVERYONE
                        (including root).
    """
    __tablename__ = "ml_permissions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    label = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True, default="")
    allowed_roles = db.Column(db.JSON, nullable=False, default=lambda: ["root"])
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "description": self.description or "",
            "allowed_roles": self.allowed_roles or [],
            "is_enabled": self.is_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Default permission seeds ─────────────────────────────────────────────

DEFAULT_PERMISSIONS = [
    {
        "key": "provider.manage",
        "label": "供应商管理",
        "description": "添加、编辑、删除分组内的供应商配置",
        "allowed_roles": ["root"],
    },
    {
        "key": "apikey.manage",
        "label": "API Key 管理",
        "description": "创建、管理和预算分组下的 API Key",
        "allowed_roles": ["root"],
    },
    {
        "key": "template.manage",
        "label": "模型模板管理",
        "description": "创建、编辑和同步模型模板",
        "allowed_roles": ["root"],
    },
    {
        "key": "group.manage",
        "label": "分组管理",
        "description": "编辑分组信息和删除分组",
        "allowed_roles": ["root"],
    },
    {
        "key": "member.manage",
        "label": "成员管理",
        "description": "邀请和移除分组成员、修改成员角色",
        "allowed_roles": ["root", "admin"],
    },
    {
        "key": "apikey.create",
        "label": "创建 API Key",
        "description": "允许成员创建自己的 API Key",
        "allowed_roles": ["root", "admin", "member"],
    },
    {
        "key": "model.priority",
        "label": "模型优先级",
        "description": "设置模型的优先级实现负载均衡",
        "allowed_roles": ["root", "admin"],
    },
    {
        "key": "model.traffic_ratio",
        "label": "模型流量配比",
        "description": "设置模型的流量配比实现负载均衡",
        "allowed_roles": ["root", "admin"],
    },
    {
        "key": "member.invite",
        "label": "邀请成员",
        "description": "邀请新成员加入分组",
        "allowed_roles": ["root", "admin"],
    },
    {
        "key": "permission.manage",
        "label": "权限管理",
        "description": "创建、编辑、删除和开关权限点",
        "allowed_roles": ["root"],
    },
    {
        "key": "apikey.copy_others",
        "label": "复制他人 API Key",
        "description": "复制或查看其他用户创建的 API Key 的完整内容",
        "allowed_roles": ["root"],
        "is_enabled": False,
    },
    {
        "key": "apikey.edit_own",
        "label": "编辑自己的 API Key",
        "description": "允许用户编辑和重新生成自己的 API Key",
        "allowed_roles": ["root", "admin", "member"],
        "is_enabled": True,
    },
    {
        "key": "tag.manage",
        "label": "标签管理",
        "description": "创建、编辑、删除系统标签定义",
        "allowed_roles": ["root"],
    },
    {
        "key": "apikey.unlimited_budget",
        "label": "不限制预算",
        "description": "开启或关闭 API Key 的不限制预算功能",
        "allowed_roles": ["root"],
    },
    {
        "key": "apikey.add_budget",
        "label": "追加预算",
        "description": "为 API Key 追加预算金额",
        "allowed_roles": ["root"],
    },
    {
        "key": "apikey.edit_models",
        "label": "编辑 API Key 可用模型",
        "description": "创建或编辑 API Key 时限制可用模型列表",
        "allowed_roles": ["root", "admin"],
    },
    {
        "key": "user.manage",
        "label": "用户管理",
        "description": "查看、创建、编辑和删除系统用户",
        "allowed_roles": ["root"],
    },
]


class Tag(db.Model):
    """Tag catalog model — defines available tag name+value pairs.

    Entities (Group, Provider, ApiKey) reference tags by storing
    [{"name": "dept", "value": "a"}, ...] in their tags JSON column.
    """
    __tablename__ = "ml_tags"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    value = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('name', 'value', name='uq_tag_name_value'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "value": self.value,
            "description": self.description or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


async def seed_default_permissions(session=None) -> list[Permission]:
    """Ensure every default permission point exists in the DB (idempotent)."""
    if session is None:
        from app import get_db_session
        async with get_db_session() as _s:
            created = await seed_default_permissions(session=_s)
            await _s.commit()
            return created

    result = await session.execute(select(Permission.key))
    existing_keys = {row[0] for row in result.all()}

    created = []
    for perm_def in DEFAULT_PERMISSIONS:
        if perm_def["key"] in existing_keys:
            continue
        perm = Permission(
            key=perm_def["key"],
            label=perm_def["label"],
            description=perm_def.get("description", ""),
            allowed_roles=perm_def["allowed_roles"],
            is_enabled=perm_def.get("is_enabled", True),
        )
        session.add(perm)
        created.append(perm)
    if created:
        await session.flush()
    return created


async def check_permission(user_role: str, permission_key: str, session=None) -> bool:
    """
    Check if a user with *user_role* is allowed to perform
    the action guarded by *permission_key*.

    Permissions are system-global — they apply uniformly across all groups.

    Logic:
      1. Permission point not found → deny (fail closed)
      2. Root role → always allow
      3. user_role in allowed_roles → allow
      4. Otherwise → deny
    """
    if session is None:
        from app import get_db_session
        async with get_db_session() as _s:
            return await check_permission(user_role, permission_key, session=_s)

    result = await session.execute(
        select(Permission).where(Permission.key == permission_key)
    )
    perm = result.scalars().first()

    if perm is None:
        return False
    if user_role == "root":
        return True
    return user_role in (perm.allowed_roles or [])


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
    # User ID (from API key's user_id); null for JWT-only or unassigned keys
    user_id = db.Column(db.Integer, nullable=True, index=True)

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
    input_price_unit = db.Column(db.Numeric(20, 10), default=0)   # $ per 1M tokens

    output_tokens = db.Column(db.BigInteger, default=0)
    output_price_unit = db.Column(db.Numeric(20, 10), default=0)  # $ per 1M tokens

    # Cache creation (Anthropic prompt caching write)
    cache_creation_tokens = db.Column(db.BigInteger, default=0)
    cache_creation_price_unit = db.Column(db.Numeric(20, 10), default=0)
    # 5-minute and 1-hour ephemeral cache creation tokens & prices
    cache_5m_creation_tokens = db.Column(db.BigInteger, default=0)
    cache_5m_creation_price_unit = db.Column(db.Numeric(20, 10), default=0)
    cache_1h_creation_tokens = db.Column(db.BigInteger, default=0)
    cache_1h_creation_price_unit = db.Column(db.Numeric(20, 10), default=0)

    # Cache hit (Anthropic prompt caching read / OpenAI cached_tokens)
    cache_tokens = db.Column(db.BigInteger, default=0)
    cache_token_price_unit = db.Column(db.Numeric(20, 10), default=0)

    # Reasoning / thinking tokens (inside output)
    reasoning_tokens = db.Column(db.BigInteger, default=0)

    # ── Image output ───────────────────────────────────────────────────────
    output_image_number = db.Column(db.Integer, default=0)
    output_image_tokens = db.Column(db.BigInteger, default=0)
    output_image_resolution = db.Column(db.String(50), nullable=True)  # e.g. "1024x1024"
    output_image_aspect = db.Column(db.String(20), nullable=True)      # e.g. "1:1"
    output_image_price_unit = db.Column(db.Numeric(20, 10), default=0)        # $ per image

    # ── Video output ───────────────────────────────────────────────────────
    output_video_number = db.Column(db.Integer, default=0)
    output_video_tokens = db.Column(db.BigInteger, default=0)
    output_video_resolution = db.Column(db.String(50), nullable=True)
    output_video_aspect = db.Column(db.String(20), nullable=True)
    output_video_seconds = db.Column(db.Float, default=0.0)
    output_video_price_unit = db.Column(db.Numeric(20, 10), default=0)

    # ── Audio output ───────────────────────────────────────────────────────
    output_audio_tokens = db.Column(db.BigInteger, default=0)
    output_audio_seconds = db.Column(db.Float, default=0.0)
    output_audio_price_unit = db.Column(db.Numeric(20, 10), default=0)

    # ── Web search ─────────────────────────────────────────────────────────
    web_search_requests = db.Column(db.Integer, default=0)
    web_search_price_unit = db.Column(db.Numeric(20, 10), default=0)  # $ per search request

    # ── 3D generation credits ──────────────────────────────────────────────
    credits = db.Column(db.Numeric(20, 10), default=0)
    credit_price_unit = db.Column(db.Numeric(20, 10), default=0)  # price per credit

    # ── Currency / exchange rate ────────────────────────────────────────────
    # Pricing currency of the model (e.g. "USD", "CNY"). Copied from Model.currency.
    currency = db.Column(db.String(10), nullable=True, default='USD')
    # Exchange rate from USD to the model's pricing currency at the time of request.
    # When currency is USD this is 1.0; when currency is CNY this is the USD→CNY rate.
    exchange_rate = db.Column(db.Numeric(20, 10), nullable=True, default=1)

    # ── Duration ───────────────────────────────────────────────────────────
    # Total wall-clock time of the request in milliseconds
    duration_ms = db.Column(db.BigInteger, nullable=True, default=None)

    # ── Billing ────────────────────────────────────────────────────────────
    # payable_amount: total cost before discount (in native currency)
    payable_amount = db.Column(db.Numeric(20, 10), nullable=True, default=0)
    # discount: discount multiplier applied (e.g. 0.9 = 10% off; 1.0 = no discount)
    discount = db.Column(db.Numeric(10, 4), nullable=True, default=1)
    # actual_amount: actual cost after discount = payable_amount * discount (in native currency)
    actual_amount = db.Column(db.Numeric(20, 10), nullable=True, default=0)
    # actual_amount_usd: actual cost in USD = actual_amount / exchange_rate
    actual_amount_usd = db.Column(db.Numeric(20, 10), nullable=True, default=0)

    # Compressed record count — 1 = single original record, >1 = merged from N records
    compressed_count = db.Column(db.Integer, default=1)

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
            'cache_5m_creation_tokens': self.cache_5m_creation_tokens,
            'cache_5m_creation_price_unit': self.cache_5m_creation_price_unit,
            'cache_1h_creation_tokens': self.cache_1h_creation_tokens,
            'cache_1h_creation_price_unit': self.cache_1h_creation_price_unit,
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
            # 3D credits
            'credits': self.credits,
            'credit_price_unit': self.credit_price_unit,
            # Currency / exchange rate
            'currency': self.currency or 'USD',
            # Billing
            'payable_amount': self.payable_amount,
            'discount': self.discount if self.discount is not None else 1.0,
            'actual_amount': self.actual_amount,
            # Duration
            'duration_ms': self.duration_ms,
            # Compression
            'compressed_count': self.compressed_count,
            # Timestamp
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ThinkingRecord(db.Model):
    """Stores reasoning/thinking content keyed by tool_call_id.

    Used by providers like DeepSeek that return reasoning_content alongside
    tool_calls but cannot accept reasoning_content echoed back in subsequent
    requests. When a follow-up turn contains a tool_result, the gateway
    looks up the saved thinking by the tool_call_id and re-injects it.
    """
    __tablename__ = "ml_thinking_records"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    thinking_id = db.Column(db.String(200), unique=True, nullable=False, index=True)
    thinking_signature = db.Column(db.Text, nullable=True)
    thinking_content = db.Column(db.Text, nullable=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class UploadedFile(db.Model):
    """Tracks files uploaded via the /v1/files endpoint.

    Maps OpenAI-compatible file_id (file-xxx) to the real object_key
    returned by the backend storage (Volcengine asset ID, S3 key, etc.).
    Used during chat request construction to resolve file references.
    """
    __tablename__ = "ml_uploaded_files"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    file_id = db.Column(db.String(200), unique=True, nullable=False, index=True)
    object_key = db.Column(db.String(500), nullable=False)
    purpose = db.Column(db.String(100), nullable=True)
    group_id = db.Column(db.Integer, nullable=True, index=True)
    api_key = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    client_user_id = db.Column(db.String(100), nullable=True)
    type = db.Column(db.String(50), nullable=False, default="volcengine")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "file_id": self.file_id,
            "object_key": self.object_key,
            "purpose": self.purpose,
            "group_id": self.group_id,
            "api_key": self.api_key,
            "user_id": self.user_id,
            "client_user_id": self.client_user_id,
            "type": self.type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }



async def get_group_models_with_shares(group_id, session=None):
    """
    Return all active models available to a group, including shared models.
    Deduplicated by model ID.
    Returns a list of (Model, Provider) tuples.
    """
    if session is None:
        from app import get_db_session
        async with get_db_session() as _s:
            return await get_group_models_with_shares(group_id, session=_s)

    # Own models — through the group's own providers
    own_result = await session.execute(
        select(Model, Provider)
        .join(Provider, Model.provider_id == Provider.id)
        .where(Provider.group_id == group_id)
        .where(Provider.is_active == True)
        .where(Model.is_active == True)
    )
    own = own_result.all()

    # Shared models — models shared TO this group from other groups
    shared_result = await session.execute(
        select(Model, Provider)
        .join(ModelShare, ModelShare.model_id == Model.id)
        .join(Provider, Model.provider_id == Provider.id)
        .where(ModelShare.target_group_id == group_id)
        .where(Provider.is_active == True)
        .where(Model.is_active == True)
    )
    shared = shared_result.all()

    # Merge and deduplicate by model id
    seen = set()
    result = []
    for model, provider in own + shared:
        if model.id in seen:
            continue
        seen.add(model.id)
        result.append((model, provider))

    return result
