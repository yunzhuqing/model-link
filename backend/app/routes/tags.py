"""
Tag management routes.

Root users can create, edit, and delete tag definitions (name/value pairs).
Entities (Group, Provider, ApiKey) reference these tags in their tags JSON column.
"""
from quart import Blueprint, request, jsonify

from app import db
from app.models import Tag, UserGroup
from app.routes.users import token_required

tags_bp = Blueprint("tags", __name__)


def _is_root_in_any_group(user_id: int) -> bool:
    count = db.session.query(UserGroup).filter(
        UserGroup.user_id == user_id,
        UserGroup.role == "root",
    ).count()
    return count > 0


def _require_root(current_user):
    if not _is_root_in_any_group(current_user.id):
        return jsonify({"detail": "Only root users can manage tags"}), 403
    return None


@tags_bp.route("/tags/", methods=["GET"])
@token_required
async def list_tags(current_user):
    """List all tag definitions."""
    tags = db.session.query(Tag).order_by(Tag.name, Tag.value).all()
    return jsonify([t.to_dict() for t in tags])


@tags_bp.route("/tags/", methods=["POST"])
@token_required
async def create_tag(current_user):
    err = _require_root(current_user)
    if err:
        return err

    data = await request.get_json()
    name = (data.get("name") or "").strip()
    value = (data.get("value") or "").strip()
    if not name or not value:
        return jsonify({"detail": "name and value are required"}), 400

    existing = db.session.query(Tag).filter(
        Tag.name == name, Tag.value == value
    ).first()
    if existing:
        return jsonify({"detail": "Tag with this name and value already exists"}), 409

    tag = Tag(
        name=name,
        value=value,
        description=(data.get("description") or "").strip(),
    )
    db.session.add(tag)
    db.session.commit()
    db.session.refresh(tag)
    return jsonify(tag.to_dict()), 201


@tags_bp.route("/tags/<int:tag_id>", methods=["PUT"])
@token_required
async def update_tag(current_user, tag_id):
    err = _require_root(current_user)
    if err:
        return err

    tag = db.session.get(Tag, tag_id)
    if not tag:
        return jsonify({"detail": "Tag not found"}), 404

    data = await request.get_json()
    name = (data.get("name") or "").strip()
    value = (data.get("value") or "").strip()
    if not name or not value:
        return jsonify({"detail": "name and value are required"}), 400

    existing = db.session.query(Tag).filter(
        Tag.name == name, Tag.value == value, Tag.id != tag_id
    ).first()
    if existing:
        return jsonify({"detail": "Tag with this name and value already exists"}), 409

    tag.name = name
    tag.value = value
    tag.description = (data.get("description") or "").strip()
    db.session.commit()
    db.session.refresh(tag)
    return jsonify(tag.to_dict())


@tags_bp.route("/tags/<int:tag_id>", methods=["DELETE"])
@token_required
async def delete_tag(current_user, tag_id):
    err = _require_root(current_user)
    if err:
        return err

    tag = db.session.get(Tag, tag_id)
    if not tag:
        return jsonify({"detail": "Tag not found"}), 404

    db.session.delete(tag)
    db.session.commit()
    return jsonify({"detail": "Tag deleted"}), 200
