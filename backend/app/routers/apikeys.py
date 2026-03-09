"""
API Key and Group management router.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import secrets
from datetime import datetime

from .. import models, schemas, database
from .users import get_current_user

router = APIRouter()


# ============== Group Management ==============

@router.get("/groups/", response_model=List[schemas.Group])
def list_groups(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """List all groups the current user belongs to"""
    return current_user.groups


@router.post("/groups/", response_model=schemas.Group, status_code=status.HTTP_201_CREATED)
def create_group(
    group: schemas.GroupCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new group"""
    # Check if group name already exists
    existing = db.query(models.Group).filter(models.Group.name == group.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group with this name already exists"
        )
    
    db_group = models.Group(
        name=group.name,
        description=group.description
    )
    db_group.users.append(current_user)  # Creator is automatically a member
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    return db_group


@router.get("/groups/{group_id}", response_model=schemas.Group)
def get_group(
    group_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get a specific group"""
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # Check if user is a member of the group
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    return group


@router.put("/groups/{group_id}", response_model=schemas.Group)
def update_group(
    group_id: int,
    group_update: schemas.GroupUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update a group"""
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # Check if user is a member of the group
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    if group_update.name is not None:
        # Check if new name already exists
        existing = db.query(models.Group).filter(
            models.Group.name == group_update.name,
            models.Group.id != group_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group with this name already exists"
            )
        group.name = group_update.name
    
    if group_update.description is not None:
        group.description = group_update.description
    
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete a group"""
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # Check if user is a member of the group
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    db.delete(group)
    db.commit()
    return None


@router.post("/groups/{group_id}/users/{user_id}", response_model=schemas.Group)
def add_user_to_group(
    group_id: int,
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Add a user to a group"""
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # Check if current user is a member of the group
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user in group.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this group"
        )
    
    group.users.append(user)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}/users/{user_id}", response_model=schemas.Group)
def remove_user_from_group(
    group_id: int,
    user_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Remove a user from a group"""
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # Check if current user is a member of the group
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a member of this group"
        )
    
    group.users.remove(user)
    db.commit()
    db.refresh(group)
    return group


# ============== API Key Management ==============

def generate_api_key() -> str:
    """Generate a secure random API key"""
    return f"ml-{secrets.token_hex(24)}"


@router.get("/api-keys/", response_model=List[schemas.ApiKeyWithGroup])
def list_api_keys(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """List all API keys for groups the user belongs to"""
    api_keys = []
    for group in current_user.groups:
        api_keys.extend(group.api_keys)
    return api_keys


@router.post("/api-keys/", response_model=schemas.ApiKey, status_code=status.HTTP_201_CREATED)
def create_api_key(
    api_key: schemas.ApiKeyCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Create a new API key"""
    # Check if the group exists and user is a member
    group = db.query(models.Group).filter(models.Group.id == api_key.group_id).first()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    if current_user not in group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group"
        )
    
    db_api_key = models.ApiKey(
        key=generate_api_key(),
        name=api_key.name,
        group_id=api_key.group_id,
        expires_at=api_key.expires_at
    )
    db.add(db_api_key)
    db.commit()
    db.refresh(db_api_key)
    return db_api_key


@router.get("/api-keys/{api_key_id}", response_model=schemas.ApiKeyWithGroup)
def get_api_key(
    api_key_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Get a specific API key"""
    api_key = db.query(models.ApiKey).filter(models.ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check if user is a member of the group
    if current_user not in api_key.group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this API key"
        )
    
    return api_key


@router.put("/api-keys/{api_key_id}", response_model=schemas.ApiKey)
def update_api_key(
    api_key_id: int,
    api_key_update: schemas.ApiKeyUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Update an API key"""
    api_key = db.query(models.ApiKey).filter(models.ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check if user is a member of the group
    if current_user not in api_key.group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this API key"
        )
    
    if api_key_update.name is not None:
        api_key.name = api_key_update.name
    
    if api_key_update.is_active is not None:
        api_key.is_active = api_key_update.is_active
    
    if api_key_update.expires_at is not None:
        api_key.expires_at = api_key_update.expires_at
    
    db.commit()
    db.refresh(api_key)
    return api_key


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    api_key_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Delete an API key"""
    api_key = db.query(models.ApiKey).filter(models.ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check if user is a member of the group
    if current_user not in api_key.group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this API key"
        )
    
    db.delete(api_key)
    db.commit()
    return None


@router.post("/api-keys/{api_key_id}/regenerate", response_model=schemas.ApiKey)
def regenerate_api_key(
    api_key_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Regenerate an API key (revokes the old one)"""
    api_key = db.query(models.ApiKey).filter(models.ApiKey.id == api_key_id).first()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Check if user is a member of the group
    if current_user not in api_key.group.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this API key"
        )
    
    api_key.key = generate_api_key()
    api_key.request_count = 0
    api_key.token_count = 0
    db.commit()
    db.refresh(api_key)
    return api_key