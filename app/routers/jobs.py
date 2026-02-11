from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import current_user, require_role
from auth.models import User

from models.jobpost import JobPost, JobPostCreate

router = APIRouter(tags=["jobs"])


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
    profession: Optional[str] = None,
    min_day_rate: Optional[float] = None,
    max_day_rate: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
):
    statement = select(JobPost).where(
        JobPost.company_id == user.id,
        JobPost.is_archived == False,  # noqa: E712
    )

    if location:
        statement = statement.where(JobPost.location.contains(location))
    if profession:
        statement = statement.where(JobPost.profession.contains(profession))
    if min_day_rate is not None:
        statement = statement.where(JobPost.day_rate_min >= min_day_rate)
    if max_day_rate is not None:
        statement = statement.where(JobPost.day_rate_max <= max_day_rate)

    statement = statement.offset(offset).limit(limit)
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
    job_update: JobPostCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    db_job = session.get(JobPost, job_id)
    if not db_job or db_job.company_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    update_data = job_update.model_dump(exclude_unset=True)
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
    profession: Optional[str] = None,
    q: Optional[str] = None,
    min_day_rate: Optional[float] = None,
    max_day_rate: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
):
    statement = select(JobPost).where(JobPost.is_archived == False)  # noqa: E712

    if location:
        statement = statement.where(JobPost.location.contains(location))
    if profession:
        statement = statement.where(JobPost.profession.contains(profession))
    if q:
        statement = statement.where(
            (JobPost.title.contains(q)) | (JobPost.description.contains(q))
        )
    if min_day_rate is not None:
        statement = statement.where(JobPost.day_rate_min >= min_day_rate)
    if max_day_rate is not None:
        statement = statement.where(JobPost.day_rate_max <= max_day_rate)

    statement = statement.offset(offset).limit(limit)
    return session.exec(statement).all()