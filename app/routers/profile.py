from fastapi import APIRouter, Depends, Body
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import current_user
from auth.models import User

from models.profile import UserProfile, UserProfileRead, UserProfileUpdate

router = APIRouter(tags=["profile"])


@router.get("/profile/me", response_model=UserProfileRead)
def get_my_profile(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.exec(
        select(UserProfile).where(UserProfile.user_id == user.id)
    ).first()

    if not profile:
        return UserProfileRead(user_id=user.id)

    return UserProfileRead(**profile.model_dump())


@router.patch("/profile/me", response_model=UserProfileRead)
def update_my_profile(
    payload: UserProfileUpdate = Body(...),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.exec(
        select(UserProfile).where(UserProfile.user_id == user.id)
    ).first()

    if not profile:
        profile = UserProfile(user_id=user.id)

    update_data = payload.model_dump(exclude_unset=True)
    update_data.pop("user_id", None)

    for key, value in update_data.items():
        setattr(profile, key, value)

    session.add(profile)
    session.commit()
    session.refresh(profile)

    return UserProfileRead(**profile.model_dump())