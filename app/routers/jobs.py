from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import current_user, require_role
from auth.models import User

from models.jobpost import JobPost, JobPostCreate, JobPostUpdate

router = APIRouter(tags=["jobs"])


# ===================== HELPERS =====================

def _contains_if_present(statement, field, value: Optional[str]):
    if value and value.strip():
        return statement.where(field.contains(value.strip()))
    return statement


# ===================== JOBS (COMPANY) =====================

@router.post("/jobs/", response_model=JobPost)
def create_job(
    job: JobPostCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job_post = JobPost(**job.model_dump(), company_id=user.id)
    session.add(job_post)
    session.commit()
    session.refresh(job_post)
    return job_post


@router.get("/jobs/", response_model=List[JobPost])
def list_jobs(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    location: Optional[str] = None,
    postcode: Optional[str] = None,
    profession: Optional[str] = None,
    profession_category: Optional[str] = None,
    engineering_discipline: Optional[str] = None,
    industry: Optional[str] = None,
    ir35_type: Optional[str] = None,
    rate_type: Optional[str] = None,
    min_day_rate: Optional[float] = None,
    max_day_rate: Optional[float] = None,
    min_hourly_rate: Optional[float] = None,
    max_hourly_rate: Optional[float] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    statement = select(JobPost).where(
        JobPost.company_id == user.id,
        JobPost.is_archived == False,  # noqa: E712
    )

    statement = _contains_if_present(statement, JobPost.location, location)
    statement = _contains_if_present(statement, JobPost.postcode, postcode)
    statement = _contains_if_present(statement, JobPost.profession, profession)
    statement = _contains_if_present(statement, JobPost.profession_category, profession_category)
    statement = _contains_if_present(statement, JobPost.engineering_discipline, engineering_discipline)
    statement = _contains_if_present(statement, JobPost.industry, industry)
    statement = _contains_if_present(statement, JobPost.ir35_type, ir35_type)
    statement = _contains_if_present(statement, JobPost.rate_type, rate_type)

    if q and q.strip():
        qv = q.strip()
        statement = statement.where(
            JobPost.title.contains(qv) | JobPost.description.contains(qv)
        )

    if min_day_rate is not None:
        statement = statement.where(JobPost.day_rate_min >= min_day_rate)
    if max_day_rate is not None:
        statement = statement.where(JobPost.day_rate_max <= max_day_rate)

    if min_hourly_rate is not None:
        statement = statement.where(JobPost.hourly_rate_min >= min_hourly_rate)
    if max_hourly_rate is not None:
        statement = statement.where(JobPost.hourly_rate_max <= max_hourly_rate)

    statement = statement.order_by(JobPost.created_at.desc()).offset(offset).limit(limit)
    return session.exec(statement).all()


@router.get("/jobs/archived", response_model=List[JobPost])
def list_archived_jobs(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
):
    statement = (
        select(JobPost)
        .where(
            JobPost.company_id == user.id,
            JobPost.is_archived == True,  # noqa: E712
        )
        .order_by(JobPost.archived_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return session.exec(statement).all()


@router.get("/jobs/{job_id}", response_model=JobPost)
def get_job(
    job_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job or job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/jobs/{job_id}", response_model=JobPost)
def update_job(
    job_id: int,
    job_update: JobPostUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    db_job = session.get(JobPost, job_id)
    if not db_job or db_job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    update_data = job_update.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(db_job, key, value)

    session.add(db_job)
    session.commit()
    session.refresh(db_job)
    return db_job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job or job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    job.is_archived = True
    job.archived_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()

    session.add(job)
    session.commit()
    return None


@router.post("/jobs/{job_id}/restore", response_model=JobPost)
def restore_job(
    job_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job or job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    job.is_archived = False
    job.archived_at = None
    job.updated_at = datetime.utcnow()

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# ===================== GLOBAL JOB SEARCH (marketplace) =====================

@router.get("/search/jobs", response_model=List[JobPost])
def search_jobs(
    user: User = Depends(require_role("company", "agency", "professional", "admin")),
    session: Session = Depends(get_session),
    location: Optional[str] = None,
    postcode: Optional[str] = None,
    profession: Optional[str] = None,
    profession_category: Optional[str] = None,
    engineering_discipline: Optional[str] = None,
    industry: Optional[str] = None,
    ir35_type: Optional[str] = None,
    rate_type: Optional[str] = None,
    q: Optional[str] = None,
    min_day_rate: Optional[float] = None,
    max_day_rate: Optional[float] = None,
    min_hourly_rate: Optional[float] = None,
    max_hourly_rate: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
):
    statement = select(JobPost).where(JobPost.is_archived == False)  # noqa: E712

    statement = _contains_if_present(statement, JobPost.location, location)
    statement = _contains_if_present(statement, JobPost.postcode, postcode)
    statement = _contains_if_present(statement, JobPost.profession, profession)
    statement = _contains_if_present(statement, JobPost.profession_category, profession_category)
    statement = _contains_if_present(statement, JobPost.engineering_discipline, engineering_discipline)
    statement = _contains_if_present(statement, JobPost.industry, industry)
    statement = _contains_if_present(statement, JobPost.ir35_type, ir35_type)
    statement = _contains_if_present(statement, JobPost.rate_type, rate_type)

    if q and q.strip():
        qv = q.strip()
        statement = statement.where(
            JobPost.title.contains(qv) | JobPost.description.contains(qv)
        )

    if min_day_rate is not None:
        statement = statement.where(JobPost.day_rate_min >= min_day_rate)
    if max_day_rate is not None:
        statement = statement.where(JobPost.day_rate_max <= max_day_rate)

    if min_hourly_rate is not None:
        statement = statement.where(JobPost.hourly_rate_min >= min_hourly_rate)
    if max_hourly_rate is not None:
        statement = statement.where(JobPost.hourly_rate_max <= max_hourly_rate)

    statement = statement.order_by(JobPost.created_at.desc()).offset(offset).limit(limit)
    return session.exec(statement).all()