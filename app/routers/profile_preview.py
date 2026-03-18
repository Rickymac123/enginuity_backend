from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth.users import fastapi_users
from auth.models import User
from auth.database import get_session

from models.talent import Talent
from models.review import Review

router = APIRouter(prefix="/professional", tags=["professional"])
current_user = fastapi_users.current_user(active=True)


def require_professional(user: User = Depends(current_user)) -> User:
    if getattr(user, "role", None) != "professional":
        raise HTTPException(status_code=403, detail="PROFESSIONAL_ONLY")
    return user


def _dump_model(obj: Any) -> Dict[str, Any]:
    # Pydantic v2 / SQLModel
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # Pydantic v1 fallback
    if hasattr(obj, "dict"):
        return obj.dict()
    # Last resort
    return dict(obj)


def _to_int_rating(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(value)
    except Exception:
        return None
    if 1 <= n <= 5:
        return n
    return None


@router.get("/me/preview")
def get_my_profile_preview(
    user: User = Depends(require_professional),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    # Pull Talent (your professional profile table)
    talent: Optional[Talent] = session.exec(
        select(Talent).where(Talent.user_id == user.id)
    ).first()

    # Verified + public reviews only (what clients see)
    reviews: List[Review] = session.exec(
        select(Review)
        .where(
            Review.professional_id == user.id,
            Review.status == "verified",
            Review.is_public == True,  # noqa: E712
        )
        .order_by(Review.verified_at.desc(), Review.created_at.desc())
    ).all()

    ratings: List[int] = []
    for r in reviews:
        n = _to_int_rating(getattr(r, "rating", None))
        if n is not None:
            ratings.append(n)

    avg = (sum(ratings) / len(ratings)) if ratings else 0.0

    # Flatten into the shape your frontend expects
    profile: Dict[str, Any] = {
        "id": user.id,
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "avatar_url": (
        getattr(talent, "avatar_url", None) if talent else None
        ) or getattr(user, "avatar_url", None),
        # Talent fields (safe even if Talent missing)
        "profession": getattr(talent, "profession", None) if talent else None,
        "location": getattr(talent, "location", None) if talent else None,
        "bio": getattr(talent, "bio", None) if talent else None,
        "skills": getattr(talent, "skills", None) if talent else None,
        "engineering_discipline": getattr(talent, "engineering_discipline", None) if talent else None,
        "industry": getattr(talent, "industry", None) if talent else None,
        "ir35_preference": getattr(talent, "ir35_preference", None) if talent else None,
        "rate_type": getattr(talent, "rate_type", None) if talent else None,
        "day_rate": getattr(talent, "day_rate", None) if talent else None,
        "hourly_rate": getattr(talent, "hourly_rate", None) if talent else None,
        "work_radius_miles": getattr(talent, "work_radius_miles", None) if talent else None,
    }

    return {
        "profile": profile,
        "reviews": [_dump_model(r) for r in reviews],
        "average_rating": round(avg, 2),
        "review_count": len(ratings),
    }