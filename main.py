from fastapi import FastAPI, Depends
from sqlmodel import SQLModel, create_engine, Session, select

# Models
from models.booking import Booking
from models.company import Company
from models.jobpost import JobPost, JobPostCreate
from models.engineer import Engineer

# Auth
from auth.users import fastapi_users, auth_backend
from auth.models import User
from auth.schemas import UserRead, UserCreate, UserUpdate 

# DB setup
from auth.database import init_db

app = FastAPI()

# === User Routes ===
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

# === SQLite DB Setup ===
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=True)

# === DB Initialization ===
@app.on_event("startup")
async def on_startup():
    await init_db()

# === Root Route ===
@app.get("/")
def read_root():
    return {"message": "Welcome to Enginuity API"}

# === Engineer Endpoints ===
@app.post("/engineers/")
def create_engineer(engineer: Engineer):
    with Session(engine) as session:
        session.add(engineer)
        session.commit()
        session.refresh(engineer)
        return engineer

@app.get("/engineers/")
def list_engineers():
    with Session(engine) as session:
        return session.exec(select(Engineer)).all()

# === Company Endpoints ===
@app.post("/companies/")
def create_company(company: Company):
    with Session(engine) as session:
        session.add(company)
        session.commit()
        session.refresh(company)
        return company

@app.get("/companies/")
def list_companies():
    with Session(engine) as session:
        return session.exec(select(Company)).all()

# === Job Post Endpoints ===
@app.post("/jobs/")
def create_job(job: JobPostCreate):
    job_post = JobPost(**job.dict())
    with Session(engine) as session:
        session.add(job_post)
        session.commit()
        session.refresh(job_post)
        return job_post

@app.get("/jobs/")
def list_jobs():
    with Session(engine) as session:
        return session.exec(select(JobPost)).all()

# === Booking Endpoints ===
@app.post("/bookings/")
def create_booking(booking: Booking):
    with Session(engine) as session:
        session.add(booking)
        session.commit()
        session.refresh(booking)
        return booking

@app.get("/bookings/")
def list_bookings():
    with Session(engine) as session:
        return session.exec(select(Booking)).all()
