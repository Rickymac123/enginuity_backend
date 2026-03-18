from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth.database import get_session
from models.qualification import Qualification
from models.talent import Talent
from auth.users import fastapi_users
from auth.models import User

router = APIRouter(tags=["qualifications"])

current_user = fastapi_users.current_user(active=True)


class QualificationCreate(BaseModel):
    name: str
    issuer: Optional[str] = None
    credential_ref: Optional[str] = None


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


@router.post("/professional/qualifications", response_model=Qualification)
def create_qualification(
    payload: QualificationCreate,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    if getattr(user, "role", None) != "professional":
        raise HTTPException(status_code=403, detail="PROFESSIONAL_ONLY")

    talent = session.exec(
        select(Talent).where(Talent.user_id == user.id)
    ).first()

    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_PROFILE_NOT_FOUND")

    qualification = Qualification(
        talent_id=talent.id,
        name=payload.name.strip(),
        issuer=payload.issuer.strip() if payload.issuer else None,
        credential_ref=payload.credential_ref.strip() if payload.credential_ref else None,
    )

    session.add(qualification)
    session.commit()
    session.refresh(qualification)
    return qualification