"""
Model Template routes — CRUD + built-in seed data.
"""
from datetime import datetime, timezone
from quart import Blueprint, request, jsonify
from sqlalchemy import select

from app import get_db_session
from app.models import ModelTemplate
from app.routes.users import token_required
from app.routes.permissions import require_template_manage
from app.data import BUILTIN_TEMPLATES

model_templates_bp = Blueprint('model_templates', __name__)


async def seed_builtin_templates(session=None):
    """
    Insert or update built-in templates in the database.

    This function is idempotent: each template is inserted if the
    (provider, label) pair does not already exist, or updated if it does.
    The same model name may appear multiple times across different providers
    or with different labels, so name alone is not a reliable uniqueness key.
    """
    if session is None:
        async with get_db_session() as _s:
            await seed_builtin_templates(session=_s)
            await _s.commit()
        return

    result = await session.execute(select(ModelTemplate))
    existing_rows = result.scalars().all()
    existing = {
        (row.provider, row.label): row
        for row in existing_rows
    }
    for tpl in BUILTIN_TEMPLATES:
        key = (tpl['provider'], tpl['label'])
        if key not in existing:
            session.add(ModelTemplate(**tpl))
        else:
            # Update existing template with latest built-in data
            db_tpl = existing[key]
            for field, value in tpl.items():
                if field not in ('provider', 'label'):
                    setattr(db_tpl, field, value)
    await session.flush()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@model_templates_bp.route('/model-templates/', methods=['GET'])
@token_required
async def list_model_templates(current_user):
    """List all model templates."""
    async with get_db_session() as session:
        result = await session.execute(
            select(ModelTemplate).order_by(
                ModelTemplate.provider, ModelTemplate.id
            )
        )
        templates = result.scalars().all()
        return jsonify([t.to_dict() for t in templates])


@model_templates_bp.route('/model-templates/', methods=['POST'])
@token_required
@require_template_manage()
async def create_model_template(current_user):
    """Create a custom model template. Root only."""
    data = await request.get_json()

    if not data.get('label') or not data.get('name') or not data.get('provider'):
        return jsonify({'detail': 'label, name and provider are required'}), 400

    # Parse retirement_time if provided as ISO string
    retirement_time = None
    if data.get('retirement_time'):
        try:
            rt_dt = datetime.fromisoformat(data['retirement_time'].replace('Z', '+00:00'))
            if rt_dt.tzinfo is not None:
                rt_dt = rt_dt.astimezone(timezone.utc).replace(tzinfo=None)
            retirement_time = rt_dt
        except (ValueError, AttributeError):
            return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400

    tpl = ModelTemplate(
        label=data['label'],
        provider=data['provider'],
        name=data['name'],
        alias=data.get('alias'),
        context_size=data.get('context_size', 4096),
        input_size=data.get('input_size', 4096),
        output_size=data.get('output_size', 4096),
        reasoning_effort=data.get('reasoning_effort') or None,
        supported_image_formats=data.get('supported_image_formats') or None,
        pricing_tiers=data.get('pricing_tiers') or None,
        output_pricing=data.get('output_pricing') or None,
        input_price=data.get('input_price', 0.0),
        output_price=data.get('output_price', 0.0),
        cache_creation_price=data.get('cache_creation_price', 0.0),
        cache_5m_creation_price=data.get('cache_5m_creation_price', 0.0),
        cache_1h_creation_price=data.get('cache_1h_creation_price', 0.0),
        cache_hit_price=data.get('cache_hit_price', 0.0),
        currency=data.get('currency') or 'USD',
        retirement_time=retirement_time,
        rpm=data.get('rpm') or None,
        tpm=data.get('tpm') or None,
        discount=data.get('discount') if data.get('discount') is not None else 1.0,
        support_kvcache=data.get('support_kvcache', False),
        support_image=data.get('support_image', False),
        support_audio=data.get('support_audio', False),
        support_video=data.get('support_video', False),
        support_file=data.get('support_file', False),
        support_web_search=data.get('support_web_search', False),
        support_tool_search=data.get('support_tool_search', False),
        support_thinking=data.get('support_thinking', False),
        support_online_image=data.get('support_online_image', False),
        support_online_video=data.get('support_online_video', False),
        support_embedding=data.get('support_embedding', False),
        timeout=data.get('timeout') or None,
    )
    async with get_db_session() as session:
        session.add(tpl)
        await session.commit()
        await session.refresh(tpl)
        return jsonify(tpl.to_dict()), 201


@model_templates_bp.route('/model-templates/<int:template_id>', methods=['PUT'])
@token_required
@require_template_manage()
async def update_model_template(current_user, template_id):
    """Update a model template. Root only."""
    async with get_db_session() as session:
        result = await session.execute(select(ModelTemplate).where(ModelTemplate.id == template_id))
        tpl = result.scalars().first()
        if not tpl:
            return jsonify({'detail': 'Template not found'}), 404

        data = await request.get_json()
        for field in [
            'label', 'provider', 'name', 'alias', 'context_size', 'input_size', 'output_size',
            'input_price', 'output_price', 'cache_creation_price', 'cache_5m_creation_price', 'cache_1h_creation_price', 'cache_hit_price',
            'currency', 'rpm', 'tpm', 'discount', 'timeout',
            'support_kvcache', 'support_image', 'support_audio', 'support_video',
            'support_file', 'support_web_search', 'support_tool_search', 'support_thinking',
            'support_online_image', 'support_online_video', 'support_embedding',
            'output_size', 'reasoning_effort', 'supported_image_formats', 'pricing_tiers', 'output_pricing',
        ]:
            if field in data:
                setattr(tpl, field, data[field])

        # Handle retirement_time separately (ISO string → datetime)
        if 'retirement_time' in data:
            rt = data['retirement_time']
            if rt:
                try:
                    rt_dt = datetime.fromisoformat(rt.replace('Z', '+00:00'))
                    if rt_dt.tzinfo is not None:
                        rt_dt = rt_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    tpl.retirement_time = rt_dt
                except (ValueError, AttributeError):
                    return jsonify({'detail': 'Invalid retirement_time format. Use ISO 8601 (e.g. 2025-01-01T00:00:00)'}), 400
            else:
                tpl.retirement_time = None

        # Normalise nullable string fields
        if tpl.reasoning_effort == '':
            tpl.reasoning_effort = None
        if tpl.supported_image_formats == '':
            tpl.supported_image_formats = None
        if not tpl.currency:
            tpl.currency = 'USD'

        await session.commit()
        await session.refresh(tpl)
        return jsonify(tpl.to_dict())


@model_templates_bp.route('/model-templates/<int:template_id>', methods=['DELETE'])
@token_required
@require_template_manage()
async def delete_model_template(current_user, template_id):
    """Delete a model template. Root only."""
    async with get_db_session() as session:
        result = await session.execute(select(ModelTemplate).where(ModelTemplate.id == template_id))
        tpl = result.scalars().first()
        if not tpl:
            return jsonify({'detail': 'Template not found'}), 404

        await session.delete(tpl)
        await session.commit()
        return '', 204


@model_templates_bp.route('/model-templates/seed', methods=['POST'])
@token_required
@require_template_manage()
async def reseed_model_templates(current_user):
    """
    Re-seed built-in templates. Root only.
    Inserts missing built-ins and updates existing ones with latest data.
    """
    async with get_db_session() as session:
        result = await session.execute(select(ModelTemplate))
        existing_rows = result.scalars().all()
        existing = {
            (row.provider, row.label): row
            for row in existing_rows
        }
        added = 0
        updated = 0
        for tpl in BUILTIN_TEMPLATES:
            key = (tpl['provider'], tpl['label'])
            if key not in existing:
                session.add(ModelTemplate(**tpl))
                added += 1
            else:
                db_tpl = existing[key]
                for field, value in tpl.items():
                    if field not in ('provider', 'label'):
                        setattr(db_tpl, field, value)
                updated += 1
        await session.commit()
        return jsonify({'added': added, 'updated': updated})
