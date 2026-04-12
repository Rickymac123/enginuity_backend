from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.jobpost import JobPost
from models.talent import Talent

router = APIRouter(tags=["company_matches"])


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _contains(a: Optional[str], b: Optional[str]) -> bool:
    aa = _norm(a)
    bb = _norm(b)
    if not aa or not bb:
        return False
    return aa in bb or bb in aa


def _rate_fits(job: JobPost, talent: Talent) -> bool:
    rate_type = _norm(getattr(talent, "rate_type", None))
    day_rate = getattr(talent, "day_rate", None)

    job_day_min = getattr(job, "day_rate_min", None)
    job_day_max = getattr(job, "day_rate_max", None)

    if rate_type == "day" and day_rate is not None:
        if job_day_min is not None and day_rate < job_day_min:
            return False
        if job_day_max is not None and day_rate > job_day_max:
            return False

    return True


def _profession_matches(job: JobPost, talent: Talent) -> bool:
    job_profession = _norm(getattr(job, "profession", None))
    talent_profession = _norm(getattr(talent, "profession", None))

    if not job_profession:
        return True

    return job_profession == talent_profession


def _discipline_matches(job: JobPost, talent: Talent) -> bool:
    job_discipline = _norm(getattr(job, "engineering_discipline", None))
    talent_discipline = _norm(getattr(talent, "engineering_discipline", None))

    if not job_discipline:
        return True

    return job_discipline == talent_discipline


def _score_match(job: JobPost, talent: Talent) -> tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _profession_matches(job, talent):
        if _norm(getattr(job, "profession", None)):
            score += 40
            reasons.append("Profession match")

    if _discipline_matches(job, talent):
        if _norm(getattr(job, "engineering_discipline", None)):
            score += 30
            reasons.append("Discipline match")

    job_industry = getattr(job, "industry", None)
    talent_industry = getattr(talent, "industry", None)
    if _norm(job_industry) and _norm(job_industry) == _norm(talent_industry):
        score += 10
        reasons.append("Industry match")

    job_ir35 = getattr(job, "ir35_type", None) or getattr(job, "ir35_preference", None)
    talent_ir35 = getattr(talent, "ir35_preference", None)
    if _norm(job_ir35) and _norm(talent_ir35):
        if _norm(talent_ir35) == "either" or _norm(job_ir35) == _norm(talent_ir35):
            score += 5
            reasons.append("IR35 fit")

    job_location = getattr(job, "location", None)
    talent_location = getattr(talent, "location", None)
    if _contains(job_location, talent_location):
        score += 5
        reasons.append("Location overlap")

    job_postcode = getattr(job, "postcode", None)
    talent_postcode = getattr(talent, "postcode", None)
    if _contains(job_postcode, talent_postcode):
        score += 5
        reasons.append("Postcode overlap")

    if _rate_fits(job, talent):
        score += 3
        reasons.append("Rate fit")

    if getattr(talent, "cv_url", None):
        score += 1
        reasons.append("CV uploaded")

    if getattr(talent, "bio", None):
        score += 1

    return score, reasons


def _full_name(talent: Talent) -> str:
    first = (getattr(talent, "first_name", None) or "").strip()
    last = (getattr(talent, "last_name", None) or "").strip()
    full = f"{first} {last}".strip()
    return full or f"Talent #{talent.id}"


@router.get("/company/jobs/{job_id}/matches", response_model=List[dict])
def get_company_job_matches(
    job_id: int,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    job = session.get(JobPost, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")

    if getattr(job, "company_id", None) != user.id:
        raise HTTPException(status_code=403, detail="NOT_YOUR_JOB")

    talents = session.exec(
        select(Talent).where(
            Talent.agency_id == None,  # noqa: E711
        )
    ).all()

    results: List[dict] = []

    for talent in talents:
        # Hard filters first
        if not _profession_matches(job, talent):
            continue

        if not _discipline_matches(job, talent):
            continue

        score, reasons = _score_match(job, talent)

        if score <= 0:
            continue

        results.append(
            {
                "talent_id": talent.id,
                "score": score,
                "match_reasons": reasons[:4],
                "talent_name": _full_name(talent),
                "talent_profession": getattr(talent, "profession", None),
                "talent_engineering_discipline": getattr(talent, "engineering_discipline", None),
                "talent_industry": getattr(talent, "industry", None),
                "talent_location": getattr(talent, "location", None),
                "talent_postcode": getattr(talent, "postcode", None),
                "talent_ir35_preference": getattr(talent, "ir35_preference", None),
                "talent_rate_type": getattr(talent, "rate_type", None),
                "talent_day_rate": getattr(talent, "day_rate", None),
                "talent_hourly_rate": getattr(talent, "hourly_rate", None),
                "talent_work_radius_miles": getattr(talent, "work_radius_miles", None),
                "talent_avatar_url": getattr(talent, "avatar_url", None),
                "talent_bio": getattr(talent, "bio", None),
                "talent_cv_url": getattr(talent, "cv_url", None),
            }
        )

    results.sort(key=lambda x: (-x["score"], x["talent_name"] or ""))
    return results