"""
API Key and Group management routes.
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import secrets

from app import db
from app.models import Group, ApiKey
from app.routes.users import token_required

apikeys_bp = Blueprint('apikeys', __name__)


def generate_api_key():
    """Generate a secure random API key with sk- prefix (OpenAI compatible)."""
    return f"sk-{secrets.token_hex(24)}"


# ============== Group Management ==============

@apikeys_bp.route('/groups/', methods=['GET'])
@token_required
def list_groups(current_user):
    """List all groups the current user belongs to."""
    return jsonify([g.to_dict() for g in current_user.groups])


@apikeys_bp.route('/groups/', methods=['POST'])
@token_required
def create_group(current_user):
    """Create a new group."""
    from app.models import UserGroup
    
    data = request.get_json()
    
    # Check if group name already exists
    existing = db.session.query(Group).filter(Group.name == data.get('name')).first()
    if existing:
        return jsonify({'detail': 'Group with this name already exists'}), 400
    
    group = Group(
        name=data.get('name'),
        description=data.get('description')
    )
    db.session.add(group)
    db.session.flush()  # Get the group ID
    
    # Creator is automatically a root member
    user_group = UserGroup(
        user_id=current_user.id,
        group_id=group.id,
        role='root'
    )
    db.session.add(user_group)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict()), 201


@apikeys_bp.route('/groups/<int:group_id>', methods=['GET'])
@token_required
def get_group(current_user, group_id):
    """Get a specific group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['PUT'])
@token_required
def update_group(current_user, group_id):
    """Update a group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    data = request.get_json()
    if 'name' in data:
        # Check if new name already exists
        existing = db.session.query(Group).filter(
            Group.name == data['name'],
            Group.id != group_id
        ).first()
        if existing:
            return jsonify({'detail': 'Group with this name already exists'}), 400
        group.name = data['name']
    
    if 'description' in data:
        group.description = data['description']
    
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@token_required
def delete_group(current_user, group_id):
    """Delete a group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    db.session.delete(group)
    db.session.commit()
    
    return '', 204


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['POST'])
@token_required
def add_user_to_group(current_user, group_id, user_id):
    """Add a user to a group."""
    from app.models import User
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    user = db.session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({'detail': 'User not found'}), 404
    
    if user in group.users:
        return jsonify({'detail': 'User is already a member of this group'}), 400
    
    group.users.append(user)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>', methods=['DELETE'])
@token_required
def remove_user_from_group(current_user, group_id, user_id):
    """Remove a user from a group."""
    from app.models import User
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    user = db.session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({'detail': 'User not found'}), 404
    
    if user not in group.users:
        return jsonify({'detail': 'User is not a member of this group'}), 400
    
    group.users.remove(user)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/invite', methods=['POST'])
@token_required
def invite_member(current_user, group_id):
    """Invite a member to a group by email."""
    from app.models import User, UserGroup
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    data = request.get_json()
    email = data.get('email')
    role = data.get('role', 'member')  # Default to member role
    
    # Validate role
    if role not in ['root', 'admin', 'member']:
        return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400
    
    if not email:
        return jsonify({'detail': 'Email is required'}), 400
    
    # Find user by email
    user = db.session.query(User).filter(User.email == email).first()
    if not user:
        return jsonify({'detail': 'User with this email not found'}), 404
    
    if user in group.users:
        return jsonify({'detail': 'User is already a member of this group'}), 400
    
    # Add user with specified role
    user_group = UserGroup(
        user_id=user.id,
        group_id=group.id,
        role=role
    )
    db.session.add(user_group)
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


@apikeys_bp.route('/groups/<int:group_id>/users/<int:user_id>/role', methods=['PUT'])
@token_required
def update_member_role(current_user, group_id, user_id):
    """Update a member's role in a group."""
    from app.models import User, UserGroup
    
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    # Check if current user is in group
    current_user_group = db.session.query(UserGroup).filter(
        UserGroup.group_id == group_id,
        UserGroup.user_id == current_user.id
    ).first()
    
    if not current_user_group:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    # Only root or admin can change roles
    if current_user_group.role not in ['root', 'admin']:
        return jsonify({'detail': 'Only root or admin can change member roles'}), 403
    
    data = request.get_json()
    new_role = data.get('role')
    
    # Validate role
    if new_role not in ['root', 'admin', 'member']:
        return jsonify({'detail': 'Invalid role. Must be root, admin, or member'}), 400
    
    # Find the user's membership
    user_group = db.session.query(UserGroup).filter(
        UserGroup.group_id == group_id,
        UserGroup.user_id == user_id
    ).first()
    
    if not user_group:
        return jsonify({'detail': 'User is not a member of this group'}), 400
    
    # Only root can change another root's role
    if user_group.role == 'root' and current_user_group.role != 'root':
        return jsonify({'detail': 'Only root can change another root\'s role'}), 403
    
    user_group.role = new_role
    db.session.commit()
    db.session.refresh(group)
    
    return jsonify(group.to_dict())


# ============== API Key Management ==============

@apikeys_bp.route('/api-keys/', methods=['GET'])
@token_required
def list_api_keys(current_user):
    """List all API keys for groups the user belongs to."""
    api_keys = []
    for group in current_user.groups:
        api_keys.extend([k.to_dict_with_group() for k in group.api_keys])
    return jsonify(api_keys)


@apikeys_bp.route('/apikeys/group/<int:group_id>', methods=['GET'])
@token_required
def list_api_keys_by_group(current_user, group_id):
    """List all API keys for a specific group."""
    group = db.session.query(Group).filter(Group.id == group_id).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    return jsonify([k.to_dict() for k in group.api_keys])


@apikeys_bp.route('/api-keys/', methods=['POST'])
@token_required
def create_api_key(current_user):
    """Create a new API key."""
    data = request.get_json()
    
    # Check if the group exists and user is a member
    group = db.session.query(Group).filter(Group.id == data.get('group_id')).first()
    if not group:
        return jsonify({'detail': 'Group not found'}), 404
    
    if current_user not in group.users:
        return jsonify({'detail': 'You are not a member of this group'}), 403
    
    api_key = ApiKey(
        key=generate_api_key(),
        name=data.get('name'),
        group_id=data.get('group_id'),
        expires_at=data.get('expires_at')
    )
    db.session.add(api_key)
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict()), 201


@apikeys_bp.route('/api-keys/<int:api_key_id>', methods=['GET'])
@token_required
def get_api_key(current_user, api_key_id):
    """Get a specific API key."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    return jsonify(api_key.to_dict_with_group())


@apikeys_bp.route('/api-keys/<int:api_key_id>', methods=['PUT'])
@token_required
def update_api_key(current_user, api_key_id):
    """Update an API key."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    data = request.get_json()
    if 'name' in data:
        api_key.name = data['name']
    if 'is_active' in data:
        api_key.is_active = data['is_active']
    if 'expires_at' in data:
        api_key.expires_at = data['expires_at']
    
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict())


@apikeys_bp.route('/api-keys/<int:api_key_id>', methods=['DELETE'])
@token_required
def delete_api_key(current_user, api_key_id):
    """Delete an API key."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    db.session.delete(api_key)
    db.session.commit()
    
    return '', 204


@apikeys_bp.route('/api-keys/<int:api_key_id>/regenerate', methods=['POST'])
@token_required
def regenerate_api_key(current_user, api_key_id):
    """Regenerate an API key (revokes the old one)."""
    api_key = db.session.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return jsonify({'detail': 'API key not found'}), 404
    
    if current_user not in api_key.group.users:
        return jsonify({'detail': 'You do not have access to this API key'}), 403
    
    api_key.key = generate_api_key()
    api_key.request_count = 0
    api_key.token_count = 0
    db.session.commit()
    db.session.refresh(api_key)
    
    return jsonify(api_key.to_dict())