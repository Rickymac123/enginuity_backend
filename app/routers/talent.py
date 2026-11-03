from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy import func

from app.db import get_session
from auth.deps import require_role
from auth.models import User

from models.talent import Talent, TalentCreate, TalentRead, TalentUpdate, AgencyTalentCreate, AgencyRepresentation

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
        return statement.where(func.lower(field).contains(value.strip().lower(), autoescape=True))
    return statement


def _record_representation(talent, evidence):
    talent.representation_confirmed_at = datetime.utcnow()
    talent.notice_provided_on = evidence.notice_provided_on
    talent.notice_delivery_method = evidence.notice_delivery_method
    talent.notice_version = "2026-11-02"


def require_representation(talent):
    if talent.agency_id and not (talent.representation_confirmed_at and talent.notice_provided_on):
        raise HTTPException(status_code=409, detail="Open this professional's agency profile and record representation authority and privacy notice delivery before applying or accepting a booking.")


@router.post("/talent/{talent_id}/representation", response_model=TalentRead)
def record_representation(talent_id: int, evidence: AgencyRepresentation,
                          user: User = Depends(require_role("agency")), session: Session = Depends(get_session)):
    talent = session.get(Talent, talent_id)
    if not talent or talent.agency_id != user.id or talent.user_id is not None:
        raise HTTPException(status_code=404, detail="TALENT_NOT_FOUND")
    _record_representation(talent, evidence)
    talent.updated_at = datetime.utcnow()
    session.add(talent); session.commit(); session.refresh(talent)
    return talent


# ===================== TALENT (AGENCY) =====================

@router.post("/talent/", response_model=TalentRead)
def create_talent(
    talent_in: AgencyTalentCreate,
    user: User = Depends(require_role("agency")),
    session: Session = Depends(get_session),
):
    data = talent_in.model_dump(exclude={"representation"})

    data.pop("agency_id", None)
    data.pop("user_id", None)
    data.pop("id", None)

    talent = Talent(**data, agency_id=user.id, user_id=None)
    _record_representation(talent, talent_in.representation)
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
            func.lower(Talent.first_name).contains(qv.lower(), autoescape=True)
            | func.lower(Talent.last_name).contains(qv.lower(), autoescape=True)
            | func.lower(Talent.bio).contains(qv.lower(), autoescape=True)
            | func.lower(Talent.skills).contains(qv.lower(), autoescape=True)
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

    from models.application import TalentApplication
    from models.booking_request import BookingRequest
    from models.qualification import Qualification
    if any(session.exec(select(model).where(model.talent_id == talent_id)).first() for model in (TalentApplication, BookingRequest, Qualification)) or talent.cv_storage_key:
        raise HTTPException(status_code=409, detail="This profile has linked records. Contact info@contractpros.co.uk for a retention-aware removal so booking and application history is preserved.")
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