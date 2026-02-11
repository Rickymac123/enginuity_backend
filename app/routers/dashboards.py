from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.booking import Booking
from models.jobpost import JobPost
from models.talent import Talent
from models.application import TalentApplication

router = APIRouter(tags=["dashboard"])


class AgencyDashboard(BaseModel):
    total_talent: int
    total_applications: int
    applications_by_status: Dict[str, int]


class CompanyDashboard(BaseModel):
    total_jobs: int
    total_applications: int
    total_bookings: int
    applications_by_status: Dict[str, int]


@router.get("/dashboard/agency", response_model=AgencyDashboard)
def get_agency_dashboard(
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    talents = session.exec(
        select(Talent).where(
            Talent.agency_id == user.id,
            Talent.user_id == None,  # noqa: E711
        )
    ).all()
    talent_ids = [t.id for t in talents]

    applications = (
        session.exec(select(TalentApplication).where(TalentApplication.talent_id.in_(talent_ids))).all()
        if talent_ids
        else []
    )

    status_counts: Dict[str, int] = {}
    for app_obj in applications:
        status_counts[app_obj.status] = status_counts.get(app_obj.status, 0) + 1

    return AgencyDashboard(
        total_talent=len(talents),
        total_applications=len(applications),
        applications_by_status=status_counts,
    )


@router.get("/dashboard/company", response_model=CompanyDashboard)
def get_company_dashboard(
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    jobs = session.exec(
        select(JobPost).where(
            JobPost.company_id == user.id,
            JobPost.is_archived == False,  # noqa: E712
        )
    ).all()
    job_ids = [j.id for j in jobs]

    applications = (
        session.exec(select(TalentApplication).where(TalentApplication.jobpost_id.in_(job_ids))).all()
        if job_ids
        else []
    )

    bookings = (
        session.exec(select(Booking).where(Booking.jobpost_id.in_(job_ids))).all()
        if job_ids
        else []
    )

    status_counts: Dict[str, int] = {}
    for app_obj in applications:
        status_counts[app_obj.status] = status_counts.get(app_obj.status, 0) + 1

    return CompanyDashboard(
        total_jobs=len(jobs),
        total_applications=len(applications),
        total_bookings=len(bookings),
        applications_by_status=status_counts,
    )