"""
Authentication utilities for Flask application.
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
import bcrypt
import hashlib
import os

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # Default: 7 days


def _pre_hash_password(password: str) -> bytes:
    """Pre-hash password with SHA256 to support arbitrary length passwords for bcrypt."""
    return hashlib.sha256(password.encode('utf-8')).digest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash. Supports arbitrary length passwords."""
    pre_hashed = _pre_hash_password(plain_password)
    return bcrypt.checkpw(pre_hashed, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Hash a password. Supports arbitrary length passwords via SHA256 pre-hashing."""
    pre_hashed = _pre_hash_password(password)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pre_hashed, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def token_required(f):
    """Decorator to require JWT token for an endpoint."""
    from functools import wraps
    from quart import request, jsonify
    from app.user_service import get_user_by_id
    import time

    @wraps(f)
    async def decorated(*args, **kwargs):
        t0 = time.perf_counter()
        token = None
        auth_header = request.headers.get('Authorization')

        if auth_header:
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'detail': 'Not authenticated'}), 401

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get('user_id')
            if user_id is None:
                return jsonify({'detail': 'Invalid token'}), 401
        except Exception:
            return jsonify({'detail': 'Invalid token'}), 401
        # Cache-first lookup; opens its own short-lived session on cache miss.
        user = await get_user_by_id(user_id)
        if user is None:
            return jsonify({'detail': 'User not found'}), 401
        return await f(current_user=user, *args, **kwargs)

    return decorated
