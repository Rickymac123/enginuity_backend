# auth/schemas.py

from typing import Literal, Optional

from fastapi_users import schemas
from pydantic import model_validator

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

    # Optional talent-ish fields (won't exist on User unless you add them to the User model)
    profession: Optional[str] = None
    location: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    bio: Optional[str] = None


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

    # Fields used to create a Talent profile when role == "professional"
    profession: Optional[str] = None
    location: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    bio: Optional[str] = None

    @model_validator(mode="after")
    def _require_talent_fields_for_professional(self):
        if self.role == "professional":
            if not (self.profession and self.profession.strip()):
                raise ValueError("profession is required when role is professional")
            if not (self.location and self.location.strip()):
                raise ValueError("location is required when role is professional")
        return self


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

    # Optional talent-ish fields
    profession: Optional[str] = None
    location: Optional[str] = None
    work_radius_miles: Optional[int] = None
    ir35_preference: Optional[str] = None
    engineering_discipline: Optional[str] = None
    industry: Optional[str] = None
    rate_type: Optional[str] = None
    day_rate: Optional[float] = None
    hourly_rate: Optional[float] = None
    bio: Optional[str] = None