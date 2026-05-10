from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import UsageRecord

# Fields aggregated from UsageRecord for incremental sync.
# Each tuple is (field_name, aggregate_expression).
AGG_FIELDS = [
    ("request_count",       func.count(UsageRecord.id)),
    ("input_tokens",        func.coalesce(func.sum(UsageRecord.input_tokens), 0)),
    ("output_tokens",       func.coalesce(func.sum(UsageRecord.output_tokens), 0)),
    ("reasoning_tokens",    func.coalesce(func.sum(UsageRecord.reasoning_tokens), 0)),
    ("total_cost_usd",     func.coalesce(func.sum(UsageRecord.actual_amount_usd), 0)),
    ("total_image_count",   func.coalesce(func.sum(UsageRecord.output_image_number), 0)),
    ("total_video_count",   func.coalesce(func.sum(UsageRecord.output_video_number), 0)),
    ("total_audio_seconds", func.coalesce(func.sum(UsageRecord.output_audio_seconds), 0)),
]

_INT_FIELDS = ('total_input_tokens', 'total_output_tokens', 'total_reasoning_tokens',
               'total_image_count', 'total_video_count')


def get_active_key_hashes(session: Session) -> dict[str, int]:
    """Return mapping of api_key_hash → max(UsageRecord.id) for keys with usage records."""
    rows = session.query(
        UsageRecord.api_key_hash,
        func.max(UsageRecord.id).label("max_id"),
    ).filter(
        UsageRecord.api_key_hash.isnot(None),
    ).group_by(
        UsageRecord.api_key_hash,
    ).all()
    return {r.api_key_hash: r.max_id for r in rows}


def compute_delta(session: Session, key_hash: str, last_stat_id: int, current_max_id: int) -> dict | None:
    """Aggregate usage records for *key_hash* with id in (last_stat_id, current_max_id].

    Returns a dict keyed by AGG_FIELDS names, or None when no matching rows exist.
    """
    row = session.query(*[expr for _, expr in AGG_FIELDS]).filter(
        UsageRecord.api_key_hash == key_hash,
        UsageRecord.id > last_stat_id,
        UsageRecord.id <= current_max_id,
    ).first()

    if not row:
        return None

    delta = {name: row[i] for i, (name, _) in enumerate(AGG_FIELDS)}
    if delta['request_count'] == 0:
        return None
    return normalize_delta(delta)


def normalize_delta(delta: dict) -> dict:
    """Coerce types: float precision, int fields, defaults."""
    delta['total_cost_usd'] = round(float(delta['total_cost_usd'] or 0), 6)
    delta['total_audio_seconds'] = round(float(delta['total_audio_seconds'] or 0), 4)
    for f in _INT_FIELDS:
        delta[f] = int(delta[f] or 0)
    delta['request_count'] = delta['request_count'] or 0
    return delta


def apply_delta_to_apikey(ak, delta: dict):
    """Add *delta* values to the cumulative counters on an ApiKey model instance (not committed)."""
    ak.request_count = (ak.request_count or 0) + delta['request_count']
    ak.total_input_tokens = (ak.total_input_tokens or 0) + delta['total_input_tokens']
    ak.total_output_tokens = (ak.total_output_tokens or 0) + delta['total_output_tokens']
    ak.total_reasoning_tokens = (ak.total_reasoning_tokens or 0) + delta['total_reasoning_tokens']
    ak.total_cost_usd = round((ak.total_cost_usd or 0) + delta['total_cost_usd'], 6)
    ak.total_image_count = (ak.total_image_count or 0) + delta['total_image_count']
    ak.total_video_count = (ak.total_video_count or 0) + delta['total_video_count']
    ak.total_audio_seconds = round((ak.total_audio_seconds or 0) + delta['total_audio_seconds'], 4)
    ak.token_count = ak.total_input_tokens + ak.total_output_tokens


def apply_delta_to_cache(cache, key: str, ak):
    """Write cumulative ApiKey counters back to the cache."""
    cached = cache.get_api_key_info(key)
    if cached is None:
        return
    cached['request_count'] = ak.request_count
    cached['total_input_tokens'] = ak.total_input_tokens
    cached['total_output_tokens'] = ak.total_output_tokens
    cached['total_reasoning_tokens'] = ak.total_reasoning_tokens
    cached['total_cost_usd'] = ak.total_cost_usd
    cached['total_image_count'] = ak.total_image_count
    cached['total_video_count'] = ak.total_video_count
    cached['total_audio_seconds'] = ak.total_audio_seconds
    cached['token_count'] = ak.token_count
    cached['budget_used'] = ak.total_cost_usd
    cache.set_api_key_info(key, cached)