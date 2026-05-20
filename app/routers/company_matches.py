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


def _split_lines(value: Optional[str]) -> List[str]:
    if not value:
        return []
    parts = []
    for line in value.replace("\r", "\n").split("\n"):
        item = line.strip().lower()
        if item:
            parts.append(item)
    return list(dict.fromkeys(parts))


def _location_matches(job: JobPost, talent: Talent) -> bool:
    job_location = getattr(job, "location", None)
    talent_location = getattr(talent, "location", None)

    job_postcode = getattr(job, "postcode", None)
    talent_postcode = getattr(talent, "postcode", None)

    return _contains(job_location, talent_location) or _contains(job_postcode, talent_postcode)


def _profession_category_matches(job: JobPost, talent: Talent) -> bool:
    job_category = _norm(getattr(job, "profession_category", None))
    talent_category = _norm(getattr(talent, "profession_category", None))

    if not job_category:
        return True
    return job_category == talent_category


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

    if job_discipline == talent_discipline:
        return True

    if talent_discipline == "multi-skilled" and job_discipline in {"electrical", "mechanical"}:
        return True

    return False


def _industry_matches(job: JobPost, talent: Talent) -> bool:
    job_industry = _norm(getattr(job, "industry", None))
    talent_industry = _norm(getattr(talent, "industry", None))

    if not job_industry:
        return True
    return job_industry == talent_industry


def _experience_matches(job: JobPost, talent: Talent) -> bool:
    job_level = _norm(getattr(job, "experience_level", None))
    talent_level = _norm(getattr(talent, "experience_level", None))

    if not job_level or not talent_level:
        return True

    ranking = {
        "junior": 1,
        "mid-level": 2,
        "senior": 3,
        "lead": 4,
        "manager": 5,
    }

    j = ranking.get(job_level)
    t = ranking.get(talent_level)

    if j is None or t is None:
        return job_level == talent_level

    return t >= j


def _ir35_matches(job: JobPost, talent: Talent) -> bool:
    job_ir35 = _norm(getattr(job, "ir35_type", None) or getattr(job, "ir35_preference", None))
    talent_ir35 = _norm(getattr(talent, "ir35_preference", None))

    if not job_ir35 or not talent_ir35:
        return True

    return talent_ir35 == "either" or talent_ir35 == job_ir35


def _rate_fits(job: JobPost, talent: Talent) -> bool:
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

    elif job_rate_type == "hour":
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


def _travel_flags_match(job: JobPost, talent: Talent) -> bool:
    if getattr(job, "requires_travel", False) and not getattr(talent, "willing_to_travel", False):
        return False
    if getattr(job, "requires_vehicle", False) and not getattr(talent, "has_vehicle", False):
        return False
    if getattr(job, "requires_own_tools", False) and not getattr(talent, "has_tools", False):
        return False
    return True


def _score_match(job: JobPost, talent: Talent) -> tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if _profession_category_matches(job, talent) and _norm(getattr(job, "profession_category", None)):
        score += 10
        reasons.append("Category match")

    if _profession_matches(job, talent) and _norm(getattr(job, "profession", None)):
        score += 20
        reasons.append("Profession match")

    if _discipline_matches(job, talent) and _norm(getattr(job, "engineering_discipline", None)):
        score += 30
        reasons.append("Discipline match")

    if _industry_matches(job, talent) and _norm(getattr(job, "industry", None)):
        score += 10
        reasons.append("Industry match")

    if _experience_matches(job, talent) and _norm(getattr(job, "experience_level", None)):
        score += 8
        reasons.append("Experience level fit")

    if _ir35_matches(job, talent) and _norm(getattr(job, "ir35_type", None)):
        score += 5
        reasons.append("IR35 fit")

    if _location_matches(job, talent):
        score += 5
        reasons.append("Location overlap")

    if _rate_fits(job, talent):
        score += 8
        reasons.append("Rate fit")

    if getattr(job, "requires_travel", False) and getattr(talent, "willing_to_travel", False):
        score += 1
        reasons.append("Travel ready")

    if getattr(job, "requires_vehicle", False) and getattr(talent, "has_vehicle", False):
        score += 1
        reasons.append("Has vehicle")

    if getattr(job, "requires_own_tools", False) and getattr(talent, "has_tools", False):
        score += 1
        reasons.append("Has own tools")

    job_required_skills = set(_split_lines(getattr(job, "required_skills", None)))
    talent_skills = set(_split_lines(getattr(talent, "skills", None)))
    if job_required_skills and talent_skills:
        overlap = job_required_skills.intersection(talent_skills)
        if overlap:
            score += min(len(overlap) * 2, 8)
            reasons.append(f"{len(overlap)} required skill match")

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
        if not _profession_category_matches(job, talent):
            continue

        if not _profession_matches(job, talent):
            continue

        if not _discipline_matches(job, talent):
            continue

        if not _travel_flags_match(job, talent):
            continue

        score, reasons = _score_match(job, talent)

        if score <= 0:
            continue

        results.append(
            {
                "talent_id": talent.id,
                "score": score,
                "match_reasons": reasons[:5],
                "talent_name": _full_name(talent),
                "talent_profession_category": getattr(talent, "profession_category", None),
                "talent_profession": getattr(talent, "profession", None),
                "talent_engineering_discipline": getattr(talent, "engineering_discipline", None),
                "talent_industry": getattr(talent, "industry", None),
                "talent_experience_level": getattr(talent, "experience_level", None),
                "talent_location": getattr(talent, "location", None),
                "talent_postcode": getattr(talent, "postcode", None),
                "talent_ir35_preference": getattr(talent, "ir35_preference", None),
                "talent_rate_type": getattr(talent, "rate_type", None),
                "talent_day_rate": getattr(talent, "day_rate", None),
                "talent_hourly_rate": getattr(talent, "hourly_rate", None),
                "talent_work_radius_miles": getattr(talent, "work_radius_miles", None),
                "talent_willing_to_travel": getattr(talent, "willing_to_travel", None),
                "talent_has_vehicle": getattr(talent, "has_vehicle", None),
                "talent_has_tools": getattr(talent, "has_tools", None),
                "talent_avatar_url": getattr(talent, "avatar_url", None),
                "talent_bio": getattr(talent, "bio", None),
                "talent_cv_url": getattr(talent, "cv_url", None),
            }
        )

    results.sort(key=lambda x: (-x["score"], x["talent_name"] or ""))
    return results