from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.talent import Talent, TalentCreate, TalentRead, TalentUpdate

router = APIRouter(tags=["talent"])


def _get_my_talent(session: Session, user: User) -> Optional[Talent]:
    return session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        )
    ).first()


def _contains_if_present(statement, field, value: Optional[str]):
    if value and value.strip():
        return statement.where(field.contains(value.strip()))
    return statement


# ===================== TALENT (AGENCY) =====================

@router.post("/talent/", response_model=TalentRead)
def create_talent(
    talent_in: TalentCreate,
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    data = talent_in.model_dump()

    data.pop("agency_id", None)
    data.pop("user_id", None)
    data.pop("id", None)

    talent = Talent(**data, agency_id=user.id, user_id=None)
    session.add(talent)
    session.commit()
    session.refresh(talent)
    return talent


@router.get("/talent/", response_model=List[TalentRead])
def list_talent(
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
    location: Optional[str] = None,
    postcode: Optional[str] = None,
    profession_category: Optional[str] = None,
    profession: Optional[str] = None,
    engineering_discipline: Optional[str] = None,
    industry: Optional[str] = None,
    experience_level: Optional[str] = None,
    ir35_preference: Optional[str] = None,
    rate_type: Optional[str] = None,
    min_day_rate: Optional[float] = None,
    max_day_rate: Optional[float] = None,
    min_hourly_rate: Optional[float] = None,
    max_hourly_rate: Optional[float] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    statement = select(Talent).where(
        Talent.agency_id == user.id,
        Talent.user_id == None,  # noqa: E711
    )

    statement = _contains_if_present(statement, Talent.location, location)
    statement = _contains_if_present(statement, Talent.postcode, postcode)
    statement = _contains_if_present(statement, Talent.profession_category, profession_category)
    statement = _contains_if_present(statement, Talent.profession, profession)
    statement = _contains_if_present(statement, Talent.engineering_discipline, engineering_discipline)
    statement = _contains_if_present(statement, Talent.industry, industry)
    statement = _contains_if_present(statement, Talent.experience_level, experience_level)
    statement = _contains_if_present(statement, Talent.ir35_preference, ir35_preference)
    statement = _contains_if_present(statement, Talent.rate_type, rate_type)

    if q and q.strip():
        qv = q.strip()
        statement = statement.where(
            Talent.first_name.contains(qv)
            | Talent.last_name.contains(qv)
            | Talent.bio.contains(qv)
            | Talent.skills.contains(qv)
        )

    if min_day_rate is not None:
        statement = statement.where(Talent.day_rate >= min_day_rate)
    if max_day_rate is not None:
        statement = statement.where(Talent.day_rate <= max_day_rate)

    if min_hourly_rate is not None:
        statement = statement.where(Talent.hourly_rate >= min_hourly_rate)
    if max_hourly_rate is not None:
        statement = statement.where(Talent.hourly_rate <= max_hourly_rate)

    statement = statement.order_by(Talent.created_at.desc()).offset(offset).limit(limit)
    return session.exec(statement).all()


@router.get("/talent/{talent_id}", response_model=TalentRead)
def get_talent(
    talent_id: int,
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    talent = session.get(Talent, talent_id)
    if (
        not talent
        or talent.agency_id != user.id
        or talent.user_id is not None
    ):
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")
    return talent


@router.patch("/talent/{talent_id}", response_model=TalentRead)
def update_talent(
    talent_id: int,
    talent_update: TalentUpdate,
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    db_talent = session.get(Talent, talent_id)
    if (
        not db_talent
        or db_talent.agency_id != user.id
        or db_talent.user_id is not None
    ):
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")

    update_data = talent_update.model_dump(exclude_unset=True)

    for k in ("id", "agency_id", "user_id", "created_at", "updated_at"):
        update_data.pop(k, None)

    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(db_talent, key, value)

    session.add(db_talent)
    session.commit()
    session.refresh(db_talent)
    return db_talent


@router.delete("/talent/{talent_id}", status_code=204)
def delete_talent(
    talent_id: int,
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    talent = session.get(Talent, talent_id)
    if (
        not talent
        or talent.agency_id != user.id
        or talent.user_id is not None
    ):
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")

    session.delete(talent)
    session.commit()
    return None


# ===================== TALENT (PROFESSIONAL) =====================

@router.post("/professional/talent", response_model=TalentRead)
def create_my_talent(
    talent_in: TalentCreate,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    existing = _get_my_talent(session, user)
    if existing:
        return existing

    data = talent_in.model_dump()

    data.pop("agency_id", None)
    data.pop("user_id", None)
    data.pop("id", None)

    talent = Talent(**data, user_id=user.id, agency_id=None)
    session.add(talent)
    session.commit()
    session.refresh(talent)
    return talent


@router.get("/professional/talent/me", response_model=TalentRead)
def get_my_talent(
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    talent = _get_my_talent(session, user)
    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_PROFILE_NOT_FOUND")
    return talent


@router.patch("/professional/talent/me", response_model=TalentRead)
def update_my_talent(
    payload: TalentUpdate,
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    talent = _get_my_talent(session, user)
    if not talent:
        raise HTTPException(status_code=404, detail="TALENT_PROFILE_NOT_FOUND")

    update_data = payload.model_dump(exclude_unset=True)

    for k in ("id", "agency_id", "user_id", "created_at", "updated_at"):
        update_data.pop(k, None)

    update_data["updated_at"] = datetime.utcnow()

    for key, value in update_data.items():
        setattr(talent, key, value)

    session.add(talent)
    session.commit()
    session.refresh(talent)
    return talent