from sqlmodel import SQLModel, Field
from typing import Optional

class Engineer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    location: str
    skills: str  # comma-separated list or JSON string
    experience_years: int
    availability: str
    rate_per_day: float
