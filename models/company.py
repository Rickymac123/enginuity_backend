# models/company.py

from typing import Optional
from sqlmodel import SQLModel, Field

class CompanyUpdate(SQLModel):
    name: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    postcode: Optional[str] = None
    logo_url: Optional[str] = None
    description: Optional[str] = None

class CompanyBase(SQLModel):
    name: str
    location: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None


class Company(CompanyBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # The user that owns this company profile (role="company")
    owner_id: int = Field(foreign_key="user.id", index=True, nullable=False)


class CompanyCreate(CompanyBase):
    """
    Payload used when creating a company profile.
    No id or owner_id; owner_id comes from logged-in user.
    """
    pass


class CompanyRead(CompanyBase):
    id: int
    owner_id: int
