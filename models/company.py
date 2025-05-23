from sqlmodel import SQLModel, Field
from typing import Optional

class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
    location: str
    industry: str  # e.g., "Food", "Pharma", "FMCG"
    contact_number: Optional[str] = None
