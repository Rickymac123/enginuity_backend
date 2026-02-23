from dotenv import load_dotenv
load_dotenv()

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


app = FastAPI(title="Enginuity API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)

# --- Your app routers ---
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

@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def read_root():
    return {"message": "Welcome to Enginuity API"}