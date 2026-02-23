# auth/schemas.py

from typing import Literal, Optional

from fastapi_users import schemas
from pydantic import EmailStr, field_validator, model_validator

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


class SubmitImportedReview(schemas.BaseModel):
    invite_token: str

    reviewer_name: str
    reviewer_email: EmailStr
    reviewer_company: Optional[str] = None
    reviewer_role: Optional[str] = None

    rating: int
    title: Optional[str] = None
    comment: str

    # reviewer checkbox (lets you hide later without deleting)
    is_public: bool = True

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: int):
        if v < 1 or v > 5:
            raise ValueError("rating must be between 1 and 5")
        return v

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, v: str):
        if not v or len(v.strip()) < 50:
            raise ValueError("comment must be at least 50 characters")
        return v.strip()