from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.users import auth_backend, fastapi_users
from auth.schemas import UserCreate, UserRead

app = FastAPI()

# CORS (adjust origins later if you want to lock it down)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes
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

# Health
@app.get("/health")
def health():
    return {"ok": True}