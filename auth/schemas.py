# auth/schemas.py

from typing import Literal, Optional
from fastapi_users import schemas

# Explicitly define allowed roles
UserRole = Literal["company", "agency", "professional", "admin"]


class UserRead(schemas.BaseUser[int]):
    email: str
    role: UserRole

    first_name: str
    last_name: str
    phone: str

    address_line1: str
    address_line2: str
    city: str
    postcode: str
    country: str

    company_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserCreate(schemas.BaseUserCreate):
    # default stays safe; frontend will explicitly send role
    role: UserRole = "company"

    first_name: str
    last_name: str
    phone: str

    address_line1: str
    address_line2: str
    city: str
    postcode: str
    country: str

    company_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserUpdate(schemas.BaseUserUpdate):
    email: Optional[str] = None
    role: Optional[UserRole] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None

    company_name: Optional[str] = None
    avatar_url: Optional[str] = None