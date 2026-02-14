from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.jobpost import JobPost
from models.talent import Talent
from models.application import TalentApplication, TalentApplicationRead, TalentApplicationUpdate

router = APIRouter(tags=["applications"])


class ProfessionalApplyCreate(BaseModel):
    notes: Optional[str] = None


def _talent_full_name(t: Talent) -> Optional[str]:
    first = (getattr(t, "first_name", None) or "").strip()
    last = (getattr(t, "last_name", None) or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def _is_engineering_profession(t: Talent) -> bool:
    prof = (getattr(t, "profession", None) or "").strip().lower()
    return prof == "engineering"


# ===================== APPLICATIONS (PROFESSIONAL APPLY) =====================

@router.post("/jobs/{job_id}/apply", response_model=TalentApplicationRead)
def professional_apply_to_job(
    job_id: int,
    payload: ProfessionalApplyCreate = Body(...),
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        )
    ).first()
    if not talent:
        raise HTTPException(status_code=404, detail="Professional profile not completed, please complete your profile before applying")

    existing = session.exec(
        select(TalentApplication).where(
            TalentApplication.jobpost_id == job_id,
            TalentApplication.talent_id == talent.id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Application already exists")

    app_obj = TalentApplication(
        jobpost_id=job_id,
        talent_id=talent.id,
        status="pending",
        notes=payload.notes,
    )
    session.add(app_obj)
    session.commit()
    session.refresh(app_obj)
    return app_obj


# ===================== APPLICATIONS (PROFESSIONAL VIEW MY APPLICATIONS) =====================

@router.get("/professional/applications", response_model=List[dict])
def professional_list_my_applications(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    my_talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        )
    ).first()

    if not my_talent:
        return []

    apps = session.exec(
        select(TalentApplication).where(TalentApplication.talent_id == my_talent.id)
    ).all()

    if not apps:
        return []

    job_ids = list({a.jobpost_id for a in apps})
    jobs = session.exec(select(JobPost).where(JobPost.id.in_(job_ids))).all()
    job_map = {j.id: j for j in jobs}

    out: List[dict] = []
    for a in apps:
        j = job_map.get(a.jobpost_id)
        out.append(
            {
                "application_id": a.id,
                "status": a.status,
                "notes": a.notes,
                "created_at": getattr(a, "created_at", None),
                "updated_at": getattr(a, "updated_at", None),
                "jobpost_id": a.jobpost_id,
                "job_title": getattr(j, "title", None) if j else None,
                "job_location": getattr(j, "location", None) if j else None,
                "job_profession": getattr(j, "profession", None) if j else None,
                "job_day_rate_min": getattr(j, "day_rate_min", None) if j else None,
                "job_day_rate_max": getattr(j, "day_rate_max", None) if j else None,
            }
        )
    return out


# ===================== APPLICATIONS (VIEW JOB APPLICATIONS) =====================

@router.get("/jobs/{job_id}/applications", response_model=List[dict])
def list_applications_for_job(
    job_id: int,
    user: User = Depends(require_role("company", "agency", "professional")),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # NOTE: This assumes JobPost.company_id stores the company user's id.
    if user.role == "company" and getattr(job, "company_id", None) != user.id:
        raise HTTPException(status_code=403, detail="Not your job")

    apps_stmt = select(TalentApplication).where(TalentApplication.jobpost_id == job_id)

    if user.role == "agency":
        talent_ids = session.exec(
            select(Talent.id).where(
                Talent.agency_id == user.id,
                Talent.user_id == None,  # noqa: E711
            )
        ).all()
        if not talent_ids:
            return []
        apps_stmt = apps_stmt.where(TalentApplication.talent_id.in_(talent_ids))

    elif user.role == "professional":
        my_talent = session.exec(
            select(Talent).where(
                Talent.user_id == user.id,
                Talent.agency_id == None,  # noqa: E711
            )
        ).first()
        if not my_talent:
            return []
        apps_stmt = apps_stmt.where(TalentApplication.talent_id == my_talent.id)

    apps = session.exec(apps_stmt).all()
    if not apps:
        return []

    talent_ids = list({a.talent_id for a in apps})
    talents = session.exec(select(Talent).where(Talent.id.in_(talent_ids))).all()
    talent_map = {t.id: t for t in talents}

    out: List[dict] = []
    for a in apps:
        t = talent_map.get(a.talent_id)

        talent_name = _talent_full_name(t) if t else None
        profession = getattr(t, "profession", None) if t else None

        out.append(
            {
                "application_id": a.id,
                "jobpost_id": a.jobpost_id,
                "status": a.status,
                "notes": a.notes,
                "created_at": getattr(a, "created_at", None),
                "updated_at": getattr(a, "updated_at", None),

                "talent_id": a.talent_id,

                # Core display fields
                "talent_name": talent_name,
                "talent_profession": profession,
                "talent_location": getattr(t, "location", None) if t else None,
                "talent_postcode": getattr(t, "postcode", None) if t else None,
                "talent_day_rate": getattr(t, "day_rate", None) if t else None,
                "talent_hourly_rate": getattr(t, "hourly_rate", None) if t else None,
                "talent_rate_type": getattr(t, "rate_type", None) if t else None,

                # Requested extras
                "talent_engineering_discipline": (
                    getattr(t, "engineering_discipline", None)
                    if (t and _is_engineering_profession(t))
                    else None
                ),
                "talent_industry": getattr(t, "industry", None) if t else None,

                # Avatar (for your applications page card image)
                "talent_avatar_url": getattr(t, "avatar_url", None) if t else None,
            }
        )

    return out


# ===================== APPLICATIONS (UPDATE) =====================

@router.patch("/applications/{application_id}", response_model=TalentApplicationRead)
def update_application(
    application_id: int,
    application_update: TalentApplicationUpdate,
    user: User = Depends(require_role("company", "agency", "professional")),
    session: Session = Depends(get_session),
):
    app_obj = session.get(TalentApplication, application_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")

    if user.role == "company":
        job = session.get(JobPost, app_obj.jobpost_id)
        if not job or getattr(job, "company_id", None) != user.id:
            raise HTTPException(status_code=403, detail="Not allowed")

    elif user.role == "agency":
        talent = session.get(Talent, app_obj.talent_id)
        if not talent or talent.agency_id != user.id or talent.user_id is not None:
            raise HTTPException(status_code=403, detail="Not allowed")

    elif user.role == "professional":
        talent = session.get(Talent, app_obj.talent_id)
        if not talent or talent.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed")

    update_data = application_update.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(app_obj, key, value)

    session.add(app_obj)
    session.commit()
    session.refresh(app_obj)
    return app_obj