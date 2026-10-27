from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.users import fastapi_users, auth_backend
from auth.schemas import UserRead, UserCreate, UserUpdate
from auth.database import init_db

from app.routers.profile import router as profile_router
from app.routers.talent import router as talent_router
from app.routers.companies import router as companies_router
from app.routers.jobs import router as jobs_router
from app.routers.applications import router as applications_router
from app.routers.bookings import router as bookings_router
from app.routers.dashboards import router as dashboards_router
from app.routers.admin import router as admin_router
from app.routers.uploads import router as uploads_router
from app.routers.availability import router as availability_router
from app.routers.reviews import router as reviews_router
from app.routers.profile_preview import router as profile_preview_router
from app.routers.qualifications import router as qualifications_router
from app.routers.booking_requests import router as booking_requests_router
from app.routers.company_matches import router as company_matches_router
from app.routers.company_talent import router as company_talent_router

from app.routers.social_auth import router as social_auth_router

app = FastAPI(title="ContractPros API")

@app.middleware("http")
async def limit_public_requests(request, call_next):
    from starlette.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    from sqlmodel import Session
    from app.db import engine
    from app.rate_limits import consume
    from urllib.parse import parse_qs
    protected = request.url.path.startswith(("/auth/", "/public/reviews/")) and request.method == "POST"
    if protected:
        # Count the actual upstream connection, not an untrusted forwarded IP header.
        client = request.client.host if request.client else "unknown"
        def network_limit():
            with Session(engine) as session:
                return consume(session, f"network:{client}", 300)
        if not await run_in_threadpool(network_limit):
            return JSONResponse({"detail":"RATE_LIMITED"}, status_code=429, headers={"Retry-After":"300"})
        if request.url.path in {"/auth/jwt/login", "/auth/forgot-password", "/auth/request-verify-token"}:
            try:
                if "application/json" in request.headers.get("content-type", ""):
                    identity = (await request.json()).get("email", "")
                else:
                    identity = parse_qs((await request.body()).decode()).get("username", [""])[0]
                if isinstance(identity, str) and identity:
                    def identity_limit():
                        with Session(engine) as session:
                            return consume(session, f"{request.url.path}:{identity.strip().lower()}", 10)
                    if not await run_in_threadpool(identity_limit):
                        return JSONResponse({"detail":"RATE_LIMITED"}, status_code=429, headers={"Retry-After":"300"})
            except (ValueError, UnicodeError, AttributeError):
                pass
    return await call_next(request)

app.include_router(social_auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "https://www.contractpros.co.uk,https://contractpros.co.uk").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- FastAPI Users routes ---
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
app.include_router(
    fastapi_users.get_auth_router(auth_backend, requires_verification=True),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])

app.include_router(qualifications_router)

app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)

# --- App routers ---
app.include_router(profile_router)
app.include_router(talent_router)
app.include_router(companies_router)
app.include_router(jobs_router)
app.include_router(applications_router)
app.include_router(bookings_router)
app.include_router(dashboards_router)
app.include_router(admin_router)
app.include_router(uploads_router)
app.include_router(availability_router)
app.include_router(reviews_router)
app.include_router(profile_preview_router)
app.include_router(booking_requests_router)
app.include_router(company_matches_router)
app.include_router(company_talent_router)

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def read_root():
    return {"message": "Welcome to ContractPros API"}