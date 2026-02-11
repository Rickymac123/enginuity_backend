from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.company import Company, CompanyCreate, CompanyRead, CompanyUpdate

router = APIRouter(tags=["companies"])


@router.post("/companies/", response_model=CompanyRead)
def create_company(
    company_in: CompanyCreate,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    # Prevent multiple company profiles per owner (simple rule)
    existing = session.exec(
        select(Company).where(Company.owner_id == user.id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Company profile already exists")

    company = Company(**company_in.model_dump(), owner_id=user.id)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


@router.get("/companies/me", response_model=CompanyRead)
def get_my_company(
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    company = session.exec(
        select(Company).where(Company.owner_id == user.id)
    ).first()

    if not company:
        raise HTTPException(status_code=404, detail="Company profile not found")

    return company


@router.patch("/companies/me", response_model=CompanyRead)
def update_my_company(
    payload: CompanyUpdate,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    company = session.exec(
        select(Company).where(Company.owner_id == user.id)
    ).first()

    if not company:
        raise HTTPException(status_code=404, detail="Company profile not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(company, key, value)

    session.add(company)
    session.commit()
    session.refresh(company)
    return company


@router.get("/companies/", response_model=List[CompanyRead])
def list_companies(
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    statement = select(Company).where(Company.owner_id == user.id)
    return session.exec(statement).all()