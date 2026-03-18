from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from auth.database import get_session
from models.qualification import Qualification
from models.talent import Talent
from auth.users import fastapi_users
from auth.models import User

router = APIRouter(tags=["qualifications"])

current_user = fastapi_users.current_user(active=True)


@router.get("/professional/qualifications", response_model=List[Qualification])
def get_my_qualifications(
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    talent = session.exec(
        select(Talent).where(Talent.user_id == user.id)
    ).first()

    if not talent:
        return []

    return session.exec(
        select(Qualification).where(Qualification.talent_id == talent.id)
    ).all()