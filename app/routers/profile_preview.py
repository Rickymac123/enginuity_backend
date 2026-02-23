from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from auth.users import fastapi_users
from auth.models import User
from auth.database import get_session

from models.talent import Talent
from models.review import Review
from models.review_verification import ReviewVerification

router = APIRouter(prefix="/professional", tags=["professional"])
current_user = fastapi_users.current_user(active=True)

@router.get("/me/preview")
def get_my_profile_preview(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    # Talent record for this user (adjust if your Talent relation differs)
    talent = session.exec(select(Talent).where(Talent.user_id == user.id)).first()

    # Verified reviews only: verification.used_at IS NOT NULL
    # Also hide reviews flagged hidden (field name may differ in your model; adjust if needed)
    q = (
        select(Review)
        .join(ReviewVerification, ReviewVerification.review_id == Review.id)
        .where(
            Review.professional_user_id == user.id,     # adjust if your FK is different
            ReviewVerification.used_at != None,         # noqa: E711
            (Review.is_hidden == False)                 # noqa: E712
        )
        .order_by(Review.created_at.desc())
    )
    reviews: List[Review] = session.exec(q).all()

    ratings = [r.rating for r in reviews if isinstance(getattr(r, "rating", None), int)]
    avg = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    return {
        "user": {
            "id": user.id,
            "first_name": getattr(user, "first_name", ""),
            "last_name": getattr(user, "last_name", ""),
            "avatar_url": getattr(user, "avatar_url", None),
        },
        "talent": (talent.model_dump() if talent else None),
        "stats": {
            "review_count": len(ratings),
            "average_rating": avg,
        },
        "reviews": [r.model_dump() for r in reviews],
    }