# models/jobpost.py

from typing import Optional
from datetime import datetime, date, time
from sqlmodel import SQLModel, Field


class JobPostBase(SQLModel):
    title: str
    description: str

    # Core classification
    profession_category: Optional[str] = None      # e.g. Engineering
    profession: Optional[str] = None               # e.g. Engineer
    engineering_discipline: Optional[str] = None   # e.g. Electrical / Mechanical / Controls
    industry: Optional[str] = None                 # e.g. Food Manufacturing

    # Location
    location: Optional[str] = None
    postcode: Optional[str] = None
    work_radius_miles: Optional[int] = None
    site_name: Optional[str] = None
    site_address: Optional[str] = None

    # Dates / times
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    shift_pattern: Optional[str] = None

    # Commercial
    rate_type: Optional[str] = None                # day / hour
    day_rate_min: Optional[float] = None
    day_rate_max: Optional[float] = None
    hourly_rate_min: Optional[float] = None
    hourly_rate_max: Optional[float] = None
    ir35_type: Optional[str] = None                # inside / outside / either

    # Requirements
    required_skills: Optional[str] = None
    preferred_skills: Optional[str] = None
    required_qualifications: Optional[str] = None
    experience_level: Optional[str] = None

    # Engagement details
    contract_type: Optional[str] = None            # contract / interim / temp / shift cover
    is_urgent: bool = False
    requires_travel: bool = False
    requires_vehicle: bool = False
    requires_own_tools: bool = False


class JobPost(JobPostBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    company_id: int = Field(foreign_key="user.id", index=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Soft delete
    is_archived: bool = Field(default=False, index=True)
    archived_at: Optional[datetime] = Field(default=None, index=True)


class JobPostCreate(JobPostBase):
    pass


class JobPostUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None

    profession_category: Optional[str] = None
    profession: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None

    location: Optional[str] = None
    postcode: Optional[str] = None
    work_radius_miles: Optional[int] = None
    site_name: Optional[str] = None
    site_address: Optional[str] = None

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    shift_pattern: Optional[str] = None

    rate_type: Optional[str] = None
    day_rate_min: Optional[float] = None
    day_rate_max: Optional[float] = None
    hourly_rate_min: Optional[float] = None
    hourly_rate_max: Optional[float] = None
    ir35_type: Optional[str] = None

    required_skills: Optional[str] = None
    preferred_skills: Optional[str] = None
    required_qualifications: Optional[str] = None
    experience_level: Optional[str] = None

    contract_type: Optional[str] = None
    is_urgent: Optional[bool] = None
    requires_travel: Optional[bool] = None
    requires_vehicle: Optional[bool] = None
    requires_own_tools: Optional[bool] = None