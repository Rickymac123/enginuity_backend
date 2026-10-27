"""Local full-app acceptance fixture; no real email or production database."""
import os, tempfile, json
from pathlib import Path
if os.environ.get('CONTRACTPROS_LOCAL_TESTS') != '1':
    raise RuntimeError('Local test opt-in required')
_directory=tempfile.TemporaryDirectory(prefix='contractpros-launch-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(_directory.name)/'test.db')
os.environ['SECRET']='local-test-only-'+('x'*48)
os.environ['FRONTEND_BASE_URL']='http://127.0.0.1:3102'
from app.main import app
from auth.users import UserManager
from app.routers import reviews
async def capture(self,user,token,request=None):
    Path(os.environ['TEST_MAIL_FILE']).write_text(json.dumps({'email':user.email,'token':token}))
UserManager.on_after_request_verify=capture
UserManager.on_after_forgot_password=capture
def review_capture(to_email,verify_url):
    Path(os.environ['TEST_MAIL_FILE']).write_text(json.dumps({'email':to_email,'url':verify_url}))
reviews.send_review_verification_email=review_capture

@app.on_event('startup')
def seed_acceptance_accounts():
    from sqlmodel import Session
    from app.db import engine
    from auth.models import User
    from fastapi_users.password import PasswordHelper
    from models.talent import Talent
    from models.company import Company
    from models.qualification import Qualification
    password=PasswordHelper().hash('Local-test-password-2026')
    with Session(engine) as session:
        for i,role in enumerate(['professional','company','agency','admin'],101):
            session.add(User(id=i,email=f'{role}@example.com',hashed_password=password,role=role,is_active=True,is_verified=True,first_name='Local',last_name='Tester'))
        session.add(Talent(id=101,user_id=101,first_name='Local',last_name='Professional',profession_category='engineering',profession='Engineer',location='London'))
        session.add(Company(id=102,owner_id=102,name='Local Company'))
        session.add(Qualification(id=101,talent_id=101,name='Local test qualification',issuer='Test issuer'))
        session.commit()
