# models/profile.py

from typing import Optional
from sqlmodel import SQLModel, Field


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profile"

    id: Optional[int] = Field(default=None, primary_key=True)

    # one-to-one with User (enforced via unique=True)
    user_id: int = Field(index=True, unique=True, nullable=False)

    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)

    address_line1: Optional[str] = Field(default=None)
    address_line2: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    postcode: Optional[str] = Field(default=None)
    country: Optional[str] = Field(default=None)

    company_name: Optional[str] = Field(default=None)


# Response / input schemas (non-table)
class UserProfileRead(SQLModel):
    user_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None
    company_name: Optional[str] = None


class UserProfileUpdate(SQLModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None
    company_name: Optional[str] = None