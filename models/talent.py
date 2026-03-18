from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class TalentBase(SQLModel):
    first_name: str
    last_name: str
    profession: str
    location: str  # required for CREATE / normal use

    postcode: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    avatar_url: Optional[str] = None
    cv_url: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None


class Talent(TalentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agency_id: Optional[int] = Field(default=None, index=True)
    user_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TalentCreate(TalentBase):
    pass


class TalentRead(SQLModel):
    id: int
    first_name: str
    last_name: str
    profession: str
    location: Optional[str] = None  # allow legacy NULLs

    postcode: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    avatar_url: Optional[str] = None
    cv_url: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None

    agency_id: Optional[int] = None
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class TalentUpdate(SQLModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profession: Optional[str] = None
    location: Optional[str] = None  # PATCH stays optional
    postcode: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    avatar_url: Optional[str] = None
    cv_url: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[str] = None