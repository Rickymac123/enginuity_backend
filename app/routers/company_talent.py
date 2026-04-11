from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.talent import Talent
from models.qualification import Qualification
from models.review import Review

router = APIRouter(tags=["company_talent"])


def _review_public_and_verified(review: Review) -> bool:
    status = (getattr(review, "status", None) or "").strip().lower()
    is_public = getattr(review, "is_public", True)
    return is_public and (not status or status == "verified")


@router.get("/company/talent/{talent_id}/profile", response_model=dict)
def get_company_talent_profile(
    talent_id: int,
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    talent = session.get(Talent, talent_id)
    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")

    qualifications = session.exec(
        select(Qualification).where(Qualification.talent_id == talent.id)
    ).all()

    reviews = session.exec(
        select(Review).where(Review.talent_id == talent.id)
    ).all()

    visible_reviews: List[Review] = [r for r in reviews if _review_public_and_verified(r)]

    avg_rating = 0.0
    if visible_reviews:
        avg_rating = sum(float(getattr(r, "rating", 0) or 0) for r in visible_reviews) / len(visible_reviews)

    profile = {
        "id": talent.id,
        "first_name": getattr(talent, "first_name", None),
        "last_name": getattr(talent, "last_name", None),
        "profession": getattr(talent, "profession", None),
        "location": getattr(talent, "location", None),
        "postcode": getattr(talent, "postcode", None),
        "bio": getattr(talent, "bio", None),
        "avatar_url": getattr(talent, "avatar_url", None),
        "engineering_discipline": getattr(talent, "engineering_discipline", None),
        "industry": getattr(talent, "industry", None),
        "ir35_preference": getattr(talent, "ir35_preference", None),
        "rate_type": getattr(talent, "rate_type", None),
        "day_rate": getattr(talent, "day_rate", None),
        "hourly_rate": getattr(talent, "hourly_rate", None),
        "work_radius_miles": getattr(talent, "work_radius_miles", None),
        "skills": getattr(talent, "skills", None),
        "cv_url": getattr(talent, "cv_url", None),
    }

    return {
        "profile": profile,
        "qualifications": qualifications,
        "reviews": visible_reviews,
        "average_rating": round(avg_rating, 1) if visible_reviews else 0.0,
        "review_count": len(visible_reviews),
    }