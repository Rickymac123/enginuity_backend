from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date

class JobPostBase(SQLModel):
    title: str
    location: str
    skills_required: str
    start_date: date
    end_date: date
    rate_per_day: float
    company_id: int

class JobPost(JobPostBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

class JobPostCreate(JobPostBase):
    pass
