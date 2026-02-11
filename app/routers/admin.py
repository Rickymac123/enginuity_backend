from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_admin
from auth.models import User
from auth.schemas import UserRead

from models.jobpost import JobPost
from models.talent import TalentRead
from models.talent import Talent
from models.booking import Booking

router = APIRouter(tags=["admin"])


class AdminUserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    is_verified: Optional[bool] = None


class AdminJobUpdate(BaseModel):
    is_archived: bool


@router.get("/admin/users", response_model=List[UserRead])
def admin_list_users(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return session.exec(select(User)).all()


@router.get("/admin/users/{user_id}", response_model=UserRead)
def admin_get_user(
    user_id: int,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@router.patch("/admin/users/{user_id}", response_model=UserRead)
def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate = Body(...),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="Admins cannot modify their own account")

    update_data = payload.dict(exclude_unset=True)
    allowed_fields = {"email", "role", "is_active", "is_superuser", "is_verified"}
    update_data = {k: v for k, v in update_data.items() if k in allowed_fields}

    if "email" in update_data and update_data["email"]:
        existing = session.exec(select(User).where(User.email == update_data["email"])).first()
        if existing and existing.id != u.id:
            raise HTTPException(status_code=400, detail="Email already in use")

    for key, value in update_data.items():
        setattr(u, key, value)

    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@router.get("/admin/talent", response_model=List[TalentRead])
def admin_list_talent(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return session.exec(select(Talent)).all()


@router.get("/admin/jobs", response_model=List[JobPost])
def admin_list_jobs(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return session.exec(select(JobPost)).all()


@router.patch("/admin/jobs/{job_id}", response_model=JobPost)
def admin_update_job(
    job_id: int,
    payload: AdminJobUpdate,
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.is_archived = bool(payload.is_archived)
    job.archived_at = datetime.utcnow() if job.is_archived else None

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/admin/bookings", response_model=List[Booking])
def admin_list_bookings(
    _: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return session.exec(select(Booking)).all()