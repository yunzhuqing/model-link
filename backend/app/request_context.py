"""
Plain-data containers passed across the request pipeline.

These dataclasses replace direct ORM object passing in the request path so that
the SQLAlchemy session can be closed before the upstream LLM call begins.
All fields are plain Python primitives (or plain containers) and are safe to
read after the originating DB session has been closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class AuthContext:
    """Snapshot of auth state extracted from ApiKey / User ORM rows.

    Populated by `gateway_helpers.get_current_user_or_api_key()` while a DB
    session is briefly open; consumed by request handlers and background usage
    recorders after the session has been closed.
    """
    # Identity
    user_id: Optional[int] = None
    user_name: Optional[str] = None

    # API key (None if authenticated via JWT)
    api_key_id: Optional[int] = None
    api_key_raw: Optional[str] = None
    api_key_name: Optional[str] = None
    api_key_group_id: Optional[int] = None
    api_key_group_name: Optional[str] = None
    api_key_workspace_id: Optional[int] = None

    # Rate-limit overrides set on the API key
    api_key_rpm: Optional[int] = None
    api_key_tpm: Optional[int] = None

    # Budget / ACL
    unlimited_budget: bool = True
    allowed_models: Optional[List[str]] = None

    # Lifecycle
    expires_at: Optional[datetime] = None
    is_active: bool = True

    # Provider override parsed from sk-xxx-{providerId}
    provider_id_override: Optional[int] = None


@dataclass
class ResolvedModelData:
    """Snapshot of resolved Model + Provider ORM rows.

    Populated by `GatewayService.resolve_model()` inside a short-lived session;
    consumed downstream after the session has been closed. The associated
    provider instance is a long-lived cached object (see GatewayService.
    _create_provider_instance) and is therefore safe to pass alongside.
    """
    # Provider
    provider_id: int = 0
    provider_name: str = ""
    provider_type: str = ""

    # Model identifiers
    model_id: int = 0
    model_alias: Optional[str] = None
    model_real_name: str = ""

    # Pricing (flat) — Decimal coerced to float so it's safe across thread/task boundaries
    input_price: float = 0.0
    output_price: float = 0.0
    cache_creation_price: float = 0.0
    cache_5m_creation_price: float = 0.0
    cache_1h_creation_price: float = 0.0
    cache_hit_price: float = 0.0
    currency: str = "USD"
    discount: float = 1.0

    # Tiered / structured pricing
    pricing_tiers: Optional[List[Dict[str, Any]]] = None
    output_pricing: Optional[Dict[str, Any]] = None

    # Capability flags
    support_thinking: bool = False
    support_online_image: bool = True
    support_online_video: bool = True

    # Multi-modal / embedding capability flags (consumed by embed/rerank/images)
    support_image: bool = False
    support_audio: bool = False
    support_video: bool = False
    support_embedding: bool = False

    # Per-model timeout override (seconds)
    timeout: Optional[int] = None

    # Supported API access types (comma-separated: chat_completions,responses,messages)
    api_type: Optional[str] = None

    # Reference to the (cached, long-lived) provider instance — populated by GatewayService
    provider_instance: Any = field(default=None, repr=False)
