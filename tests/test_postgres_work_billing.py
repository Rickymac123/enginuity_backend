"""Disposable PostgreSQL rehearsal for migration and timesheet races."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, time
import pytest
from fastapi import FastAPI, Request, Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, select
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers.work_billing import router
from models.booking import Booking
from models.talent import Talent
from models.work_billing import BookingRate, WorkTimesheet, WorkInvoice, WorkAudit
from scripts.prepare_launch import migrate

pytestmark = pytest.mark.skipif(os.getenv('CONTRACTPROS_POSTGRES_TESTS') != '1', reason='Disposable PostgreSQL not configured')

@pytest.fixture
def pg_work(monkeypatch):
    url = os.environ['TEST_POSTGRES_URL']
    assert make_url(url).host in {'localhost', '127.0.0.1', 'postgres'}
    monkeypatch.setenv('WORK_INVOICING_ENABLED', 'false')
    schema = 'test_work_' + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        # Rehearse an additive upgrade from an existing schema, twice.
        new_tables = {'workbillingsettings', 'bookingrate', 'workaudit', 'worktimesheet', 'workinvoice', 'quickbooksclient', 'quickbooksconnection', 'quickbooksflow'}
        SQLModel.metadata.create_all(engine, tables=[t for t in SQLModel.metadata.sorted_tables if t.name not in new_tables])
        migrate(engine)
        migrate(engine)
        with Session(engine) as s:
            s.add_all([User(id=i,email=f'{i}@example.test',hashed_password='unused',role=role,is_active=True,is_verified=True) for i,role in [(1,'professional'),(2,'company')]])
            s.commit()
            s.add(Talent(id=1,user_id=1,first_name='Test',last_name='Person',profession='Engineer',profession_category='engineering',location='UK'))
            s.commit()
            s.add(Booking(id=1,booking_request_id=1,company_id=2,talent_id=1,start_date=date(2026,1,1),end_date=date(2026,1,31),start_time=time(8),end_time=time(17),site_name='Test',site_address='UK',contact_name='Test',contact_phone='0',client_payment_due_days=7))
            s.commit()
            s.add(BookingRate(booking_id=1,contractor_pence=4000,markup_bps=2000,recorded_by=2))
            s.commit()
        app = FastAPI()
        app.include_router(router)
        def db():
            with Session(engine) as s: yield s
        def who(request: Request,s: Session=Depends(get_session)):
            return s.get(User,int(request.headers['x-test-user']))
        app.dependency_overrides[get_session] = db
        app.dependency_overrides[current_user] = who
        yield app, engine
    finally:
        engine.dispose()
        with admin.begin() as c: c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()

def submit_body():
    return {'week_start':'2026-01-05','expected_revision':0,'entries':[{'start':'2026-01-05T08:00','end':'2026-01-05T17:00','break_minutes':60}]}

def race(app, calls):
    barrier = Barrier(len(calls))
    def run(call):
        path, body, user = call
        with TestClient(app) as c:
            barrier.wait(timeout=10)
            return c.post(path,json=body,headers={'x-test-user':str(user)}).status_code
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return sorted(pool.map(run,calls))

def test_duplicate_submission_is_serialised(pg_work):
    app,engine = pg_work
    call = ('/work-billing/bookings/1/timesheets',submit_body(),1)
    assert race(app,[call,call]) == [200,409]
    with Session(engine) as s: assert len(s.exec(select(WorkTimesheet)).all()) == 1

@pytest.mark.parametrize('second_action',['approve','return'])
def test_approval_races_do_not_duplicate_or_overwrite(pg_work,second_action):
    app,engine = pg_work
    with TestClient(app) as c:
        result=c.post('/work-billing/bookings/1/timesheets',json=submit_body(),headers={'x-test-user':'1'})
        assert result.status_code == 200
        sid=result.json()['id']
    base=f'/work-billing/timesheets/{sid}'
    outcomes=race(app,[(base+'/approve',{'expected_revision':1},2),(base+'/'+second_action,{'expected_revision':1,'reason':'Check break'},2)])
    assert outcomes == ([200,200] if second_action=='approve' else [200,409])
    with Session(engine) as s:
        row=s.get(WorkTimesheet,sid)
        assert row.revision == 2
        assert not s.exec(select(WorkInvoice)).all()
        actions=s.exec(select(WorkAudit).where(WorkAudit.entity=='timesheet',WorkAudit.entity_id==sid,WorkAudit.action.in_(['approved','returned']))).all()
        assert len(actions)==1
