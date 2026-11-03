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
    user: User = Depends(require_role("company", "agency")),
    session: Session = Depends(get_session),
):
    if not company_in.name.strip():
        raise HTTPException(status_code=422, detail="Business name is required")
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
    user: User = Depends(require_role("company", "agency")),
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
    user: User = Depends(require_role("company", "agency")),
    session: Session = Depends(get_session),
):
    company = session.exec(
        select(Company).where(Company.owner_id == user.id)
    ).first()

    if not company:
        raise HTTPException(status_code=404, detail="Company profile not found")

    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("name", "existing") is None or not str(update_data.get("name", "existing")).strip():
        raise HTTPException(status_code=422, detail="Business name is required")
    if "is_public" in update_data and update_data["is_public"] is None:
        raise HTTPException(status_code=422, detail="Publication choice is required")
    for key, value in update_data.items():
        setattr(company, key, value)

    session.add(company)
    session.commit()
    session.refresh(company)
    return company


@router.get("/companies/", response_model=List[CompanyRead])
def list_companies(
    user: User = Depends(require_role("company", "agency")),
    session: Session = Depends(get_session),
):
    statement = select(Company).where(Company.owner_id == user.id)
    return session.exec(statement).all()

@router.get("/businesses/{owner_id}")
def business_profile(owner_id: int, session: Session = Depends(get_session)):
    from models.jobpost import JobPost
    owner = session.get(User, owner_id)
    company = session.exec(select(Company).where(Company.owner_id == owner_id)).first()
    if not owner or not owner.is_active or owner.role not in {"company", "agency"} or not company or not company.is_public:
        raise HTTPException(status_code=404, detail="This business has not published a profile yet")
    # Deliberate allowlist: never expose email, postcode, user flags or site contacts.
    def safe_url(value):
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(value or "")
            return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None
        except ValueError:
            return None
    jobs = session.exec(select(JobPost).where(JobPost.company_id == owner_id, JobPost.is_archived == False).order_by(JobPost.created_at.desc())).all()
    return {"name": company.name, "business_id": owner_id, "account_type": owner.role,
        "description": company.description, "industry": company.industry, "location": company.location,
        "website": safe_url(company.website), "logo_url": safe_url(company.logo_url),
        "registration_number": company.registration_number,
        "jobs": [{"id": j.id, "title": j.title, "location": j.location, "profession": j.profession} for j in jobs]}
