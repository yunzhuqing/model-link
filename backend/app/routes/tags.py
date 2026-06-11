"""
Tag management routes.

Root users can create, edit, and delete tag definitions (name/value pairs).
Entities (Group, Provider, ApiKey) reference these tags in their tags JSON column.
"""
import time
import logging

from quart import Blueprint, request, jsonify
from sqlalchemy import select

from app import get_db_session
from app.models import Tag, UserGroup
from app.auth import token_required

tags_bp = Blueprint("tags", __name__)
logger = logging.getLogger(__name__)


async def _is_root_in_any_group(session, user_id: int) -> bool:
    result = await session.execute(
        select(UserGroup).where(
            UserGroup.user_id == user_id,
            UserGroup.role == "root",
        )
    )
    count = len(result.scalars().all())
    return count > 0


async def _require_root(session, current_user):
    if not await _is_root_in_any_group(session, current_user.id):
        return jsonify({"detail": "Only root users can manage tags"}), 403
    return None


@tags_bp.route("/tags/", methods=["GET"])
@token_required
async def list_tags(current_user):
    """List all tag definitions."""
    t0 = time.perf_counter()
    async with get_db_session() as session:
        result = await session.execute(select(Tag).order_by(Tag.name, Tag.value))
        tags = result.scalars().all()
        t1 = time.perf_counter()
        result = [t.to_dict() for t in tags]
    t2 = time.perf_counter()
    logger.info(
        "list_tags user=%s total=%.3fms db_query=%.3fms serialize=%.3fms count=%d",
        current_user.username, (t2 - t0) * 1000, (t1 - t0) * 1000, (t2 - t1) * 1000, len(result),
    )
    return jsonify(result)


@tags_bp.route("/tags/", methods=["POST"])
@token_required
async def create_tag(current_user):
    async with get_db_session() as session:
        err = await _require_root(session, current_user)
        if err:
            return err

        data = await request.get_json()
        name = (data.get("name") or "").strip()
        value = (data.get("value") or "").strip()
        if not name or not value:
            return jsonify({"detail": "name and value are required"}), 400

        result = await session.execute(
            select(Tag).where(Tag.name == name, Tag.value == value)
        )
        existing = result.scalars().first()
        if existing:
            return jsonify({"detail": "Tag with this name and value already exists"}), 409

        tag = Tag(
            name=name,
            value=value,
            description=(data.get("description") or "").strip(),
        )
        session.add(tag)
        await session.commit()
        await session.refresh(tag)
        return jsonify(tag.to_dict()), 201


@tags_bp.route("/tags/<int:tag_id>", methods=["PUT"])
@token_required
async def update_tag(current_user, tag_id):
    async with get_db_session() as session:
        err = await _require_root(session, current_user)
        if err:
            return err

        tag = await session.get(Tag, tag_id)
        if not tag:
            return jsonify({"detail": "Tag not found"}), 404

        data = await request.get_json()
        name = (data.get("name") or "").strip()
        value = (data.get("value") or "").strip()
        if not name or not value:
            return jsonify({"detail": "name and value are required"}), 400

        result = await session.execute(
            select(Tag).where(Tag.name == name, Tag.value == value, Tag.id != tag_id)
        )
        existing = result.scalars().first()
        if existing:
            return jsonify({"detail": "Tag with this name and value already exists"}), 409

        tag.name = name
        tag.value = value
        tag.description = (data.get("description") or "").strip()
        await session.commit()
        await session.refresh(tag)
        return jsonify(tag.to_dict())


@tags_bp.route("/tags/<int:tag_id>", methods=["DELETE"])
@token_required
async def delete_tag(current_user, tag_id):
    async with get_db_session() as session:
        err = await _require_root(session, current_user)
        if err:
            return err

        tag = await session.get(Tag, tag_id)
        if not tag:
            return jsonify({"detail": "Tag not found"}), 404

        await session.delete(tag)
        await session.commit()
        return jsonify({"detail": "Tag deleted"}), 200
