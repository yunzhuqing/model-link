from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from .. import models, schemas, database
from .users import get_current_user
from typing import List

router = APIRouter()

# Provider Endpoints
@router.post("/providers/", response_model=schemas.Provider)
def create_provider(provider: schemas.ProviderCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_provider = models.Provider(**provider.dict())
    db.add(db_provider)
    db.commit()
    db.refresh(db_provider)
    return db_provider

@router.get("/providers/", response_model=List[schemas.Provider])
def read_providers(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    providers = db.query(models.Provider).offset(skip).limit(limit).all()
    return providers

@router.put("/providers/{provider_id}", response_model=schemas.Provider)
def update_provider(provider_id: int, provider: schemas.ProviderUpdate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not db_provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    update_data = provider.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_provider, key, value)
    
    db.commit()
    db.refresh(db_provider)
    return db_provider

@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not db_provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.delete(db_provider)
    db.commit()
    return None

# Model Endpoints
@router.post("/models/", response_model=schemas.Model)
def create_model(model: schemas.ModelCreate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_model = models.Model(**model.dict())
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    return db_model

@router.put("/models/{model_id}", response_model=schemas.Model)
def update_model(model_id: int, model: schemas.ModelUpdate, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_model = db.query(models.Model).filter(models.Model.id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    update_data = model.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_model, key, value)
    
    db.commit()
    db.refresh(db_model)
    return db_model

@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(get_current_user)):
    db_model = db.query(models.Model).filter(models.Model.id == model_id).first()
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    db.delete(db_model)
    db.commit()
    return None
