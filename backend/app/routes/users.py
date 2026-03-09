"""
User authentication and management routes.
"""
from flask import Blueprint, request, jsonify
from datetime import timedelta
from functools import wraps
import os

from app import db
from app.models import User
from app.auth import verify_password, get_password_hash, create_access_token
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from typing import Optional, List

users_bp = Blueprint('users', __name__)

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


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


def token_required(f):
    """Decorator to require JWT token for an endpoint."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header:
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        
        if not token:
            return jsonify({'detail': 'Not authenticated'}), 401
        
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get('sub')
            if username is None:
                return jsonify({'detail': 'Invalid token'}), 401
        except JWTError:
            return jsonify({'detail': 'Invalid token'}), 401
        
        user = db.session.query(User).filter(User.username == username).first()
        if user is None:
            return jsonify({'detail': 'User not found'}), 401
        
        return f(current_user=user, *args, **kwargs)
    
    return decorated


@users_bp.route('/register', methods=['POST'])
def register():
    """Register a new user."""
    data = request.get_json()
    
    try:
        user_create = UserCreate(**data)
    except Exception as e:
        return jsonify({'detail': str(e)}), 400
    
    # Check if username exists
    existing_user = db.session.query(User).filter(User.username == user_create.username).first()
    if existing_user:
        return jsonify({'detail': 'Username already registered'}), 400
    
    # Create user
    hashed_password = get_password_hash(user_create.password)
    user = User(
        username=user_create.username,
        email=user_create.email,
        hashed_password=hashed_password
    )
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    
    return jsonify(user.to_dict()), 201


@users_bp.route('/token', methods=['POST'])
def login():
    """Login and get access token."""
    # Handle both form data and JSON
    if request.is_json:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
    else:
        username = request.form.get('username')
        password = request.form.get('password')
    
    if not username or not password:
        return jsonify({'detail': 'Username and password required'}), 400
    
    user = db.session.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return jsonify({'detail': 'Incorrect username or password'}), 401
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': user.username},
        expires_delta=access_token_expires
    )
    
    return jsonify({
        'access_token': access_token,
        'token_type': 'bearer'
    })


@users_bp.route('/users/me', methods=['GET'])
@token_required
def get_current_user_info(current_user):
    """Get current user info."""
    return jsonify(current_user.to_dict())


@users_bp.route('/users/<int:user_id>', methods=['DELETE'])
@token_required
def delete_user(current_user, user_id):
    """Delete a user."""
    if user_id != current_user.id:
        return jsonify({'detail': 'Not authorized to delete this user'}), 403
    
    user = db.session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({'detail': 'User not found'}), 404
    
    db.session.delete(user)
    db.session.commit()
    
    return '', 204