# app/routers/uploads.py

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from auth.deps import require_role
from auth.models import User
from app.db import get_session
from app.storage.r2 import r2_client, bucket_name, public_base_url
from models.talent import Talent
from models.company import Company  # <-- add this import

router = APIRouter(tags=["uploads"])

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}

MAX_CV_BYTES = 15 * 1024 * 1024  # 15MB
ALLOWED_CV_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
}

# NEW: company logo
MAX_COMPANY_LOGO_BYTES = 5 * 1024 * 1024  # 5MB
ALLOWED_COMPANY_LOGO_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _get_my_talent_or_404(session: Session, user: User) -> Talent:
    talent = session.exec(
        select(Talent).where(
            Talent.user_id == user.id,
            Talent.agency_id == None,  # noqa: E711
        )
    ).first()

    if not talent:
        raise HTTPException(status_code=404, detail="Talent profile not found")

    return talent


# NEW: helpers for company
def _get_my_company_or_404(session: Session, user: User) -> Company:
    company = session.exec(
        select(Company).where(
            Company.user_id == user.id,
        )
    ).first()

    if not company:
        raise HTTPException(status_code=404, detail="Company profile not found")

    return company


@router.post("/uploads/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="Invalid avatar file type")

    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar too large (max 5MB)")

    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[file.content_type]

    key = f"avatars/user_{user.id}.{ext}"

    s3 = r2_client()
    s3.put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=data,
        ContentType=file.content_type,
        CacheControl="public, max-age=31536000",
    )

    url = f"{public_base_url().rstrip('/')}/{key}"

    talent = _get_my_talent_or_404(session, user)
    talent.avatar_url = url
    talent.updated_at = datetime.utcnow()
    session.add(talent)
    session.commit()

    return {"url": url, "key": key}


@router.post("/uploads/cv")
async def upload_cv(
    file: UploadFile = File(...),
    user: User = Depends(require_role("professional")),
    session: Session = Depends(get_session),
):
    if file.content_type not in ALLOWED_CV_TYPES:
        raise HTTPException(status_code=400, detail="Invalid CV file type (PDF or DOCX only)")

    data = await file.read()
    if len(data) > MAX_CV_BYTES:
        raise HTTPException(status_code=400, detail="CV too large (max 15MB)")

    ext = "pdf" if file.content_type == "application/pdf" else "docx"
    key = f"cvs/user_{user.id}.{ext}"

    s3 = r2_client()
    s3.put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=data,
        ContentType=file.content_type,
        ContentDisposition=f'attachment; filename="{file.filename or f"cv.{ext}"}"',
        CacheControl="private, max-age=0, no-cache",
    )

    url = f"{public_base_url().rstrip('/')}/{key}"

    talent = _get_my_talent_or_404(session, user)
    talent.cv_url = url
    talent.updated_at = datetime.utcnow()
    session.add(talent)
    session.commit()

    return {"url": url, "key": key, "filename": file.filename, "content_type": file.content_type}


# ===================== COMPANY UPLOADS =====================

@router.post("/uploads/company-logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    if file.content_type not in ALLOWED_COMPANY_LOGO_TYPES:
        raise HTTPException(status_code=400, detail="Invalid company logo file type")

    data = await file.read()
    if len(data) > MAX_COMPANY_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Company logo too large (max 5MB)")

    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[file.content_type]

    key = f"company-logos/user_{user.id}.{ext}"

    s3 = r2_client()
    s3.put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=data,
        ContentType=file.content_type,
        CacheControl="public, max-age=31536000",
    )

    url = f"{public_base_url().rstrip('/')}/{key}"

    company = _get_my_company_or_404(session, user)
    # adjust field name if your Company model uses something else (e.g. logo_url)
    company.logo_url = url
    company.updated_at = datetime.utcnow()
    session.add(company)
    session.commit()

    return {"url": url, "key": key}