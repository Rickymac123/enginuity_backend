# app/routers/uploads.py

from datetime import datetime
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from fastapi.responses import RedirectResponse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from auth.deps import require_role
from auth.models import User
from app.db import get_session
from app.storage.r2 import r2_client, bucket_name, public_base_url, private_bucket_name
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


async def read_upload(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if not data or len(data) > limit:
        raise HTTPException(status_code=400, detail="File is empty or exceeds the size limit")
    kind = file.content_type
    valid = False
    if kind == "application/pdf": valid = data.startswith(b"%PDF-")
    elif kind == "image/png": valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif kind == "image/jpeg": valid = data.startswith(b"\xff\xd8\xff")
    elif kind == "image/webp": valid = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif kind == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            with ZipFile(BytesIO(data)) as archive:
                valid = "word/document.xml" in archive.namelist() and "[Content_Types].xml" in archive.namelist()
        except BadZipFile: pass
    if not valid:
        raise HTTPException(status_code=400, detail="File contents do not match the selected file type")
    return data


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
            Company.owner_id == user.id,
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

    data = await read_upload(file, MAX_AVATAR_BYTES)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar too large (max 5MB)")

    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[file.content_type]

    talent = _get_my_talent_or_404(session, user)
    key = f"avatars/{uuid4().hex}.{ext}"

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
    talent = _get_my_talent_or_404(session, user)
    try: bucket = private_bucket_name()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Private document storage is not configured yet")
    data = await read_upload(file, MAX_CV_BYTES)
    ext = "pdf" if file.content_type == "application/pdf" else "docx"
    key = f"cvs/{uuid4().hex}.{ext}"
    s3 = r2_client()
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=file.content_type,
        ContentDisposition=f'attachment; filename="cv.{ext}"', CacheControl="private, no-store")
    talent.cv_storage_key = key
    talent.cv_url = f"/api/uploads/cv/{talent.id}"
    talent.updated_at = datetime.utcnow()
    session.add(talent)
    session.commit()
    return {"url": talent.cv_url, "filename": f"cv.{ext}", "content_type": file.content_type}


@router.get("/uploads/cv/{talent_id}")
def download_cv(talent_id: int,
    user: User = Depends(require_role("professional", "company", "agency", "admin")),
    session: Session = Depends(get_session)):
    talent = session.get(Talent, talent_id)
    if not talent:
        raise HTTPException(status_code=404, detail="CV_NOT_FOUND")
    # Companies can read recruitment profiles. Other professionals cannot read each other's CVs.
    if not (user.role in {"company", "admin"} or talent.user_id == user.id or talent.agency_id == user.id):
        raise HTTPException(status_code=403, detail="NOT_ALLOWED")
    if not talent.cv_storage_key:
        raise HTTPException(status_code=404, detail="CV_NOT_FOUND")
    try: bucket = private_bucket_name()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Private document storage is not configured yet")
    url = r2_client().generate_presigned_url("get_object", Params={"Bucket":bucket,"Key":talent.cv_storage_key}, ExpiresIn=60)
    return RedirectResponse(url, status_code=307, headers={"Cache-Control":"private, no-store", "Referrer-Policy":"no-referrer"})


# ===================== COMPANY UPLOADS =====================

@router.post("/uploads/company-logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    user: User = Depends(require_role("company")),
    session: Session = Depends(get_session),
):
    if file.content_type not in ALLOWED_COMPANY_LOGO_TYPES:
        raise HTTPException(status_code=400, detail="Invalid company logo file type")

    data = await read_upload(file, MAX_COMPANY_LOGO_BYTES)
    if len(data) > MAX_COMPANY_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="Company logo too large (max 5MB)")

    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[file.content_type]

    company = _get_my_company_or_404(session, user)
    key = f"company-logos/{uuid4().hex}.{ext}"

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