"""
User authentication and management routes.
"""
from quart import Blueprint, request, jsonify
from datetime import timedelta
import os
import logging

from sqlalchemy import select, func
from app import get_db_session
from app.models import User
from app.user_service import get_user_by_id, invalidate_user_cache
from app.auth import verify_password, get_password_hash, create_access_token, token_required
from app.routes.permissions import require_global_permission
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from typing import Optional, List

logger = logging.getLogger(__name__)

users_bp = Blueprint('users', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # Default: 7 days


# Pydantic schemas for validation
class UserCreate(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    groups: List[dict] = []


@users_bp.route('/register', methods=['POST'])
async def register():
    """Register a new user."""
    data = await request.get_json()

    try:
        user_create = UserCreate(**data)
    except Exception as e:
        return jsonify({'detail': str(e)}), 400

    async with get_db_session() as session:
        # Check if username exists
        result = await session.execute(select(User).where(User.username == user_create.username))
        existing_user = result.scalars().first()
        if existing_user:
            return jsonify({'detail': 'Username already registered'}), 400

        # Create user
        hashed_password = get_password_hash(user_create.password)
        user = User(
            username=user_create.username,
            email=user_create.email,
            hashed_password=hashed_password
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return jsonify(user.to_dict()), 201


@users_bp.route('/token', methods=['POST'])
async def login():
    """Login and get access token."""
    # Handle both form data and JSON
    if request.is_json:
        data = await request.get_json()
        username = data.get('username')
        password = data.get('password')
    else:
        form = await request.form
        username = form.get('username')
        password = form.get('password')

    if not username or not password:
        return jsonify({'detail': 'Username and password required'}), 400

    async with get_db_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalars().first()
        if not user or not verify_password(password, user.hashed_password):
            return jsonify({'detail': 'Incorrect username or password'}), 401

        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={'sub': user.username, 'user_id': user.id},
            expires_delta=access_token_expires
        )

        return jsonify({
            'access_token': access_token,
            'token_type': 'bearer'
        })


@users_bp.route('/users/me', methods=['GET'])
@token_required
async def get_current_user_info(current_user):
    """Get current user info."""
    return jsonify(current_user.to_dict())


@users_bp.route('/users/<int:user_id>', methods=['DELETE'])
@token_required
async def delete_user(current_user, user_id):
    """Delete a user."""
    if user_id != current_user.id:
        return jsonify({'detail': 'Not authorized to delete this user'}), 403

    async with get_db_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return jsonify({'detail': 'User not found'}), 404

        await session.delete(user)
        await session.commit()

    await invalidate_user_cache(user_id)

    return '', 204


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None


@users_bp.route('/api/users', methods=['GET'])
@token_required
@require_global_permission('user.manage')
async def list_users(current_user):
    """List all users with pagination and optional search.

    Query params:
        page     — page number (1-based, default 1)
        per_page — items per page (default 20, max 100)
        search   — filter by username or email (case-insensitive)
    """
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search', '').strip()

    async with get_db_session() as session:
        conditions = []
        if search:
            pattern = f'%{search}%'
            conditions.append(
                (User.username.ilike(pattern)) | (User.email.ilike(pattern))
            )

        # Count total
        count_q = select(func.count(User.id))
        if conditions:
            count_q = count_q.where(*conditions)
        total_result = await session.execute(count_q)
        total = total_result.scalar() or 0

        # Fetch page
        offset = (page - 1) * per_page
        data_q = select(User).order_by(User.id).offset(offset).limit(per_page)
        if conditions:
            data_q = data_q.where(*conditions)

        result = await session.execute(data_q)
        users = result.scalars().all()

        return jsonify({
            'data': [u.to_dict() for u in users],
            'total': total,
            'page': page,
            'per_page': per_page,
        })


@users_bp.route('/api/users', methods=['POST'])
@token_required
@require_global_permission('user.manage')
async def create_user_admin(current_user):
    """Admin endpoint to create a new user."""
    data = await request.get_json()

    try:
        user_create = UserCreate(**data)
    except Exception as e:
        return jsonify({'detail': str(e)}), 400

    async with get_db_session() as session:
        # Check if username exists
        result = await session.execute(select(User).where(User.username == user_create.username))
        if result.scalars().first():
            return jsonify({'detail': 'Username already registered'}), 400

        # Check if email exists
        if user_create.email:
            result = await session.execute(select(User).where(User.email == user_create.email))
            if result.scalars().first():
                return jsonify({'detail': 'Email already registered'}), 400

        hashed_password = get_password_hash(user_create.password)
        user = User(
            username=user_create.username,
            email=user_create.email,
            hashed_password=hashed_password,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return jsonify(user.to_dict()), 201


@users_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@token_required
@require_global_permission('user.manage')
async def update_user(current_user, user_id):
    """Update a user's username, email, or password."""
    data = await request.get_json()

    try:
        user_update = UserUpdate(**data)
    except Exception as e:
        return jsonify({'detail': str(e)}), 400

    async with get_db_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return jsonify({'detail': 'User not found'}), 404

        if user_update.username is not None and user_update.username != user.username:
            existing = await session.execute(
                select(User).where(User.username == user_update.username, User.id != user_id)
            )
            if existing.scalars().first():
                return jsonify({'detail': 'Username already taken'}), 400
            user.username = user_update.username

        if user_update.email is not None and user_update.email != user.email:
            existing = await session.execute(
                select(User).where(User.email == user_update.email, User.id != user_id)
            )
            if existing.scalars().first():
                return jsonify({'detail': 'Email already taken'}), 400
            user.email = user_update.email

        if user_update.password is not None:
            user.hashed_password = get_password_hash(user_update.password)

        await session.commit()
        await session.refresh(user)

    await invalidate_user_cache(user_id)

    return jsonify(user.to_dict())


@users_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@token_required
@require_global_permission('user.manage')
async def delete_user_admin(current_user, user_id):
    """Delete a user (admin endpoint)."""
    async with get_db_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return jsonify({'detail': 'User not found'}), 404

        await session.delete(user)
        await session.commit()

    await invalidate_user_cache(user_id)

    return '', 204
