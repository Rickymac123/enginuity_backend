"""PostgreSQL race test; only disposable local/CI database URLs are permitted."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from threading import Barrier
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, select
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers.booking_requests import router
from models.talent import Talent
from models.booking_request import BookingRequest
from models.booking import Booking
from models.availability import Availability
from scripts.prepare_launch import migrate

@pytest.mark.skipif(os.getenv('CONTRACTPROS_POSTGRES_TESTS') != '1', reason='Disposable PostgreSQL not configured')
def test_concurrent_booking_acceptance():
    url=os.environ['TEST_POSTGRES_URL']
    assert make_url(url).host in {'127.0.0.1','localhost','postgres'}
    schema='test_'+uuid.uuid4().hex
    admin=create_engine(url)
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:
        SQLModel.metadata.create_all(engine);migrate(engine);migrate(engine)
        with Session(engine) as s:
            user=User(id=1,email='test@example.com',hashed_password='unused',role='professional',is_active=True,is_verified=True)
            s.add(user);s.add(Talent(id=1,user_id=1,first_name='Test',last_name='Professional',profession_category='engineering',profession='Engineer',location='London'))
            for id in [1,2]:
                s.add(BookingRequest(id=id,company_id=id+1,talent_id=1,start_date=date(2027,1,4),end_date=date(2027,1,5),start_time=time(9),end_time=time(17),site_name='Test',site_address='Test',contact_name='Test',contact_phone='Test'))
            s.commit()
            s.refresh(user);s.expunge(user)
        app=FastAPI();app.include_router(router)
        def db():
            with Session(engine) as s:yield s
        app.dependency_overrides[get_session]=db;app.dependency_overrides[current_user]=lambda:user
        barrier=Barrier(2)
        def accept(id):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.post(f'/professional/booking-requests/{id}/accept').status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(accept,[1,2]))
        assert sorted(outcomes)==[200,409]
        with Session(engine) as s:assert len(s.exec(select(Booking)).all())==1
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()
