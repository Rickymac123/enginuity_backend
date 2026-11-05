from typing import List, Optional
import re
from datetime import datetime, time, timedelta
from models.booking import Booking
from models.qualification import Qualification
from app.routers.availability import _conflict_exists

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

    return list(dict.fromkeys(part.strip().lower() for part in re.split(r"[,;\r\n]+", value) if part.strip()))


def _profession_category_matches(job: JobPost, talent: Talent) -> bool:
    job_value = _norm(getattr(job, "profession_category", None))
    talent_value = _norm(getattr(talent, "profession_category", None))

    if not job_value:
        return True

    return job_value == talent_value


def _profession_matches(job: JobPost, talent: Talent) -> bool:
    job_value = _norm(getattr(job, "profession", None))
    talent_value = _norm(getattr(talent, "profession", None))

    if not job_value:
        return True

    return job_value == talent_value


def _discipline_matches(job: JobPost, talent: Talent) -> bool:
    job_value = re.sub(r"[-\s]", "", _norm(getattr(job, "engineering_discipline", None)))
    talent_value = re.sub(r"[-\s]", "", _norm(getattr(talent, "engineering_discipline", None)))

    if not job_value:
        return True

    if job_value == talent_value:
        return True

    if talent_value == "multiskilled" and job_value in {"electrical", "mechanical"}:
        return True

    return False


def _industry_matches(job: JobPost, talent: Talent) -> bool:
    job_value = _norm(getattr(job, "industry", None))
    talent_value = _norm(getattr(talent, "industry", None))

    if not job_value:
        return True

    return job_value == talent_value


def _experience_matches(job: JobPost, talent: Talent) -> bool:
    job_value = _norm(getattr(job, "experience_level", None))
    talent_value = _norm(getattr(talent, "experience_level", None))

    if not job_value:
        return True
    if not talent_value:
        return False

    ranking = {
        "junior": 1,
        "mid-level": 2,
        "senior": 3,
        "lead": 4,
        "manager": 5,
    }

    job_rank = ranking.get(job_value)
    talent_rank = ranking.get(talent_value)

    if job_rank is None or talent_rank is None:
        return job_value == talent_value

    return talent_rank >= job_rank


def _location_matches(job: JobPost, talent: Talent) -> bool:
    return (
        _contains(getattr(job, "location", None), getattr(talent, "location", None))
        or _contains(getattr(job, "postcode", None), getattr(talent, "postcode", None))
    )


def _ir35_matches(job: JobPost, talent: Talent) -> bool:
    job_value = _norm(getattr(job, "ir35_type", None) or getattr(job, "ir35_preference", None))
    talent_value = _norm(getattr(talent, "ir35_preference", None))

    if not job_value:
        return True
    if not talent_value:
        return False
    return job_value == "either" or talent_value == "either" or talent_value == job_value


def _rate_fits(job: JobPost, talent: Talent) -> bool:
    job_rate_type = _norm(getattr(job, "rate_type", None))
    talent_rate_type = _norm(getattr(talent, "rate_type", None))

    if job_rate_type and talent_rate_type and job_rate_type != talent_rate_type:
        return False

    if job_rate_type == "hour":
        talent_rate = getattr(talent, "hourly_rate", None)
        job_min = getattr(job, "hourly_rate_min", None)
        job_max = getattr(job, "hourly_rate_max", None)
    else:
        talent_rate = getattr(talent, "day_rate", None)
        job_min = getattr(job, "day_rate_min", None)
        job_max = getattr(job, "day_rate_max", None)

    if talent_rate is None:
        return False

    if job_min is not None and talent_rate < job_min:
        return False

    if job_max is not None and talent_rate > job_max:
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


def _match_details(job: JobPost, talent: Talent, qualifications=None) -> dict:
    # Percentage of the weighted criteria actually supplied, not a probability
    # of hiring success. Missing profile information never earns a match.
    criteria = [
        (bool(_norm(job.profession_category)), 10, _profession_category_matches(job, talent), "Category match"),
        (bool(_norm(job.profession)), 20, _profession_matches(job, talent), "Profession match"),
        (bool(_norm(job.engineering_discipline)), 30, _discipline_matches(job, talent), "Discipline match"),
        (bool(_norm(job.industry)), 10, _industry_matches(job, talent), "Industry match"),
        (bool(_norm(job.experience_level)), 8, _experience_matches(job, talent), "Experience fit"),
        (bool(_norm(job.ir35_type)), 5, _ir35_matches(job, talent), "IR35 fit"),
        (bool(_norm(job.location) or _norm(job.postcode)), 5, _location_matches(job, talent), "Location text overlap"),
        (any(v is not None for v in [job.day_rate_min, job.day_rate_max, job.hourly_rate_min, job.hourly_rate_max]), 8, _rate_fits(job, talent), "Rate fit"),
        (job.requires_travel, 1, talent.willing_to_travel, "Travel ready"),
        (job.requires_vehicle, 1, talent.has_vehicle, "Has vehicle"),
        (job.requires_own_tools, 1, talent.has_tools, "Has own tools"),
    ]
    total = sum(weight for present, weight, match, reason in criteria if present)
    earned = sum(weight for present, weight, match, reason in criteria if present and match)
    reasons = [reason for present, weight, match, reason in criteria if present and match]
    gaps = [reason + " not established" for present, weight, match, reason in criteria if present and not match]
    required = set(_split_lines(job.required_skills))
    if required:
        overlap = required.intersection(_split_lines(talent.skills))
        total += 8
        earned += 8 * len(overlap) / len(required)
        if overlap:
            reasons.append(f"{len(overlap)} of {len(required)} required skills listed")
        if required - overlap:
            gaps.append("Required skills not listed: " + ", ".join(sorted(required - overlap)))
    required_quals = set(_split_lines(job.required_qualifications))
    if required_quals and qualifications is not None:
        listed = {_norm(q.name) for q in qualifications}
        missing = required_quals - listed
        total += 5
        if missing:
            gaps.append("Required qualifications not listed: " + ", ".join(sorted(missing)))
        else:
            earned += 5
            reasons.append("Required qualifications listed (verify evidence)")
    return {"match_percentage": round(100 * earned / total) if total else 0,
            "match_reasons": reasons, "mismatch_reasons": gaps}


def _score_match(job: JobPost, talent: Talent, qualifications=None) -> tuple[int, List[str]]:
    details = _match_details(job, talent, qualifications)
    return details["match_percentage"], details["match_reasons"]


def _available_for_job(session, job, talent):
    if not job.start_date or not job.end_date:
        return True
    if job.end_date < job.start_date or (job.end_date - job.start_date).days > 366:
        return False
    start_time = job.start_time or time.min
    end_time = job.end_time or time.max
    if end_time <= start_time:
        return False
    existing = session.exec(select(Booking).where(Booking.talent_id == talent.id,
        Booking.status != "cancelled", Booking.start_date <= job.end_date, Booking.end_date >= job.start_date,
        Booking.start_time < end_time, Booking.end_time > start_time)).first()
    if existing:
        return False
    day = job.start_date
    while talent.user_id and day <= job.end_date:
        if _conflict_exists(session, talent.user_id, datetime.combine(day, start_time), datetime.combine(day, end_time)):
            return False
        day += timedelta(days=1)
    return True


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

    if job.is_archived:
        raise HTTPException(status_code=409, detail="JOB_CLOSED")

    talents = session.exec(
        select(Talent).where(
            Talent.agency_id == None,  # noqa: E711
        )
    ).all()

    results: List[dict] = []

    for talent in talents:
        owner = session.get(User, talent.user_id) if talent.user_id else None
        if not owner or not owner.is_active or not owner.is_verified:
            continue
        if not _available_for_job(session, job, talent):
            continue
        required = set(_split_lines((job.required_qualifications or "").replace(",", "\n")))
        qualifications = session.exec(select(Qualification).where(Qualification.talent_id == talent.id)).all()
        if required and not required.issubset({_norm(q.name) for q in qualifications}):
            continue
        if not _profession_category_matches(job, talent):
            continue

        if not _profession_matches(job, talent):
            continue

        if not _discipline_matches(job, talent):
            continue

        if not _travel_flags_match(job, talent):
            continue

        score, reasons = _score_match(job, talent, qualifications)

        results.append(
            {
                "talent_id": talent.id,
                "score": score,
                "match_reasons": reasons,
                "talent_skills": talent.skills,

                "talent_name": _full_name(talent),
                "talent_profession_category": getattr(talent, "profession_category", None),
                "talent_profession": getattr(talent, "profession", None),
                "talent_engineering_discipline": getattr(talent, "engineering_discipline", None),
                "talent_industry": getattr(talent, "industry", None),
                "talent_experience_level": getattr(talent, "experience_level", None),

                "talent_location": getattr(talent, "location", None),
                "talent_postcode": getattr(talent, "postcode", None),
                "talent_work_radius_miles": getattr(talent, "work_radius_miles", None),

                "talent_ir35_preference": getattr(talent, "ir35_preference", None),
                "talent_rate_type": getattr(talent, "rate_type", None),
                "talent_day_rate": getattr(talent, "day_rate", None),
                "talent_hourly_rate": getattr(talent, "hourly_rate", None),

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