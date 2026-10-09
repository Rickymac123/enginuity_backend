"""Create additive social-auth tables and prune expired temporary flows.

Run explicitly with the intended DATABASE_URL after a staging migration check.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from dotenv import load_dotenv
load_dotenv()
from app.db import engine
from auth.models import User  # registers the referenced user table
from models.social_auth import SocialIdentity, SocialFlow, RegistrationEmail
from sqlmodel import SQLModel, Session
from sqlalchemy import delete

if __name__ == '__main__':
    SQLModel.metadata.create_all(engine, tables=[SocialIdentity.__table__, SocialFlow.__table__, RegistrationEmail.__table__])
    with Session(engine) as session:
        result = session.exec(delete(SocialFlow).where(SocialFlow.expires_at < int(time.time())))
        session.commit()
        print(f'Social-auth tables ready; expired temporary flows removed: {result.rowcount}')
