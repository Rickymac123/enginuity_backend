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
from models.qualification import Qualification
from models.review import Review

router = APIRouter(tags=["applications"])


class ProfessionalApplyCreate(BaseModel):
    notes: Optional[str] = None


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _talent_full_name(t: Talent) -> Optional[str]:
    first = (getattr(t, "first_name", None) or "").strip()
    last = (getattr(t, "last_name", None) or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def _contains(a: Optional[str], b: Optional[str]) -> bool:
    aa = _norm(a)
    bb = _norm(b)
    if not aa or not bb:
        return False
    return aa in bb or bb in aa


def _split_csv_or_lines(value: Optional[str]) -> List[str]:
    if not value:
        return []
    raw = value.replace("\r", "\n")
    parts: List[str] = []
    for chunk in raw.split("\n"):
        for item in chunk.split(","):
            v = item.strip().lower()
            if v:
                parts.append(v)
    return list(dict.fromkeys(parts))


def _rate_match(job: JobPost, talent: Talent) -> bool:
    job_rate_type = _norm(getattr(job, "rate_type", None))
    talent_rate_type = _norm(getattr(talent, "rate_type", None))

    if job_rate_type and talent_rate_type and job_rate_type != talent_rate_type:
        return False

    if job_rate_type == "day":
        talent_day_rate = getattr(talent, "day_rate", None)
        job_day_min = getattr(job, "day_rate_min", None)
        job_day_max = getattr(job, "day_rate_max", None)

        if talent_day_rate is None:
            return False
        if job_day_min is not None and talent_day_rate < job_day_min:
            return False
        if job_day_max is not None and talent_day_rate > job_day_max:
            return False
        return True

    if job_rate_type == "hour":
        talent_hourly_rate = getattr(talent, "hourly_rate", None)
        job_hourly_min = getattr(job, "hourly_rate_min", None)
        job_hourly_max = getattr(job, "hourly_rate_max", None)

        if talent_hourly_rate is None:
            return False
        if job_hourly_min is not None and talent_hourly_rate < job_hourly_min:
            return False
        if job_hourly_max is not None and talent_hourly_rate > job_hourly_max:
            return False
        return True

    return True


def _job_talent_match(job: JobPost, talent: Talent, qualifications: List[Qualification]) -> dict:
    total_weight = 0
    achieved = 0

    matches: List[str] = []
    mismatches: List[str] = []

    def check(label: str, condition: bool, weight: int):
        nonlocal total_weight, achieved
        total_weight += weight
        if condition:
            achieved += weight
            matches.append(label)
        else:
            mismatches.append(label)

    # Hard/important criteria
    job_profession = _norm(getattr(job, "profession", None))
    talent_profession = _norm(getattr(talent, "profession", None))
    check("Profession match", not job_profession or job_profession == talent_profession, 20)

    job_discipline = _norm(getattr(job, "engineering_discipline", None))
    talent_discipline = _norm(getattr(talent, "engineering_discipline", None))
    check("Discipline match", not job_discipline or job_discipline == talent_discipline, 25)

    job_industry = _norm(getattr(job, "industry", None))
    talent_industry = _norm(getattr(talent, "industry", None))
    check("Industry match", not job_industry or job_industry == talent_industry, 10)

    job_ir35 = _norm(getattr(job, "ir35_type", None))
    talent_ir35 = _norm(getattr(talent, "ir35_preference", None))
    ir35_ok = (
        not job_ir35
        or not talent_ir35
        or talent_ir35 == "either"
        or talent_ir35 == job_ir35
    )
    check("IR35 fit", ir35_ok, 10)

    location_ok = (
        not _norm(getattr(job, "location", None))
        or _contains(getattr(job, "location", None), getattr(talent, "location", None))
        or _contains(getattr(job, "postcode", None), getattr(talent, "postcode", None))
    )
    check("Location fit", location_ok, 10)

    check("Rate fit", _rate_match(job, talent), 10)

    # Skills
    required_skills = set(_split_csv_or_lines(getattr(job, "required_skills", None)))
    talent_skills = set(_split_csv_or_lines(getattr(talent, "skills", None)))
    skills_ok = not required_skills or required_skills.issubset(talent_skills)
    check("Required skills match", skills_ok, 10)

    # Qualifications
    required_qualifications = set(
        _split_csv_or_lines(getattr(job, "required_qualifications", None))
    )
    talent_qualification_names = {
        _norm(getattr(q, "name", None)) for q in qualifications if getattr(q, "name", None)
    }
    quals_ok = not required_qualifications or required_qualifications.issubset(
        talent_qualification_names
    )
    check("Required qualifications match", quals_ok, 5)

    percentage = round((achieved / total_weight) * 100) if total_weight > 0 else 0

    return {
        "match_percentage": percentage,
        "match_reasons": matches,
        "mismatch_reasons": mismatches,
    }


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
        raise HTTPException(
            status_code=404,
            detail="Professional profile not completed, please complete your profile before applying",
        )

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
                "company_id": getattr(j, "company_id", None) if j else None,
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

    qualifications = session.exec(
        select(Qualification).where(Qualification.talent_id.in_(talent_ids))
    ).all()
    qualifications_map: dict[int, List[Qualification]] = {}
    for q in qualifications:
        qualifications_map.setdefault(q.talent_id, []).append(q)

    out: List[dict] = []
    for a in apps:
        t = talent_map.get(a.talent_id)
        t_quals = qualifications_map.get(a.talent_id, [])
        match_info = _job_talent_match(job, t, t_quals) if t else {
            "match_percentage": 0,
            "match_reasons": [],
            "mismatch_reasons": [],
        }

        out.append(
            {
                "application_id": a.id,
                "jobpost_id": a.jobpost_id,
                "status": a.status,
                "notes": a.notes,
                "created_at": getattr(a, "created_at", None),
                "updated_at": getattr(a, "updated_at", None),

                "talent_id": a.talent_id,
                "talent_name": _talent_full_name(t) if t else None,
                "talent_profession": getattr(t, "profession", None) if t else None,
                "talent_location": getattr(t, "location", None) if t else None,
                "talent_postcode": getattr(t, "postcode", None) if t else None,
                "talent_day_rate": getattr(t, "day_rate", None) if t else None,
                "talent_hourly_rate": getattr(t, "hourly_rate", None) if t else None,
                "talent_rate_type": getattr(t, "rate_type", None) if t else None,
                "talent_engineering_discipline": getattr(t, "engineering_discipline", None) if t else None,
                "talent_industry": getattr(t, "industry", None) if t else None,
                "talent_avatar_url": getattr(t, "avatar_url", None) if t else None,

                "match_percentage": match_info["match_percentage"],
                "match_reasons": match_info["match_reasons"],
                "mismatch_reasons": match_info["mismatch_reasons"],
            }
        )

    out.sort(key=lambda x: x["match_percentage"], reverse=True)
    return out


# ===================== COMPANY VIEW PROFESSIONAL PROFILE =====================

@router.get("/company/applications/{application_id}/professional-profile", response_model=dict)
def company_get_application_professional_profile(
    application_id: int,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    app_obj = session.get(TalentApplication, application_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="APPLICATION_NOT_FOUND")

    job = session.get(JobPost, app_obj.jobpost_id)
    if not job or getattr(job, "company_id", None) != user.id:
        raise HTTPException(status_code=403, detail="NOT_ALLOWED")

    talent = session.get(Talent, app_obj.talent_id)
    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")

    qualifications = session.exec(
        select(Qualification).where(Qualification.talent_id == talent.id)
    ).all()

    reviews = session.exec(
        select(Review).where(
            Review.professional_id == talent.user_id,
            Review.status == "verified",
            Review.is_public == True,  # noqa: E712
        )
    ).all()

    ratings = [r.rating for r in reviews if r.rating is not None]
    avg = sum(ratings) / len(ratings) if ratings else 0

    return {
        "profile": {
            "first_name": talent.first_name,
            "last_name": talent.last_name,
            "avatar_url": talent.avatar_url,
            "profession": talent.profession,
            "location": talent.location,
            "bio": talent.bio,
            "skills": talent.skills,
            "engineering_discipline": talent.engineering_discipline,
            "industry": talent.industry,
            "day_rate": talent.day_rate,
            "hourly_rate": talent.hourly_rate,
            "rate_type": talent.rate_type,
        },
        "qualifications": qualifications,
        "reviews": reviews,
        "average_rating": avg,
        "review_count": len(reviews),
    }


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

    new_status = update_data.get("status")
    new_notes = update_data.get("notes", app_obj.notes)

    if new_status == "rejected" and not (new_notes or "").strip():
        raise HTTPException(status_code=400, detail="REJECTION_REASON_REQUIRED")

    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(app_obj, key, value)

    session.add(app_obj)
    session.commit()
    session.refresh(app_obj)
    return app_obj