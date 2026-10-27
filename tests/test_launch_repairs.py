from datetime import date, time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.routers import companies, jobs, applications, booking_requests, uploads, bookings
from models.talent import Talent
from models.availability import Availability
from models.booking import Booking
from models.company import Company
from models.application import TalentApplication

@pytest.fixture
def context():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        pro=User(id=1,email='pro@example.com',hashed_password='unused',role='professional',is_active=True,is_verified=True)
        co=User(id=2,email='co@example.com',hashed_password='unused',role='company',is_active=True,is_verified=True)
        s.add_all([pro,co,Talent(id=1,user_id=1,first_name='Test',last_name='Pro',profession_category='engineering',profession='Engineer',location='London')]);s.commit()
        active=[co];app=FastAPI()
        for module in [companies,jobs,applications,booking_requests,uploads,bookings]:app.include_router(module.router)
        def db():yield s
        app.dependency_overrides[get_session]=db;app.dependency_overrides[current_user]=lambda:active[0]
        yield TestClient(app),s,active,pro,co
    engine.dispose()

def payload():
    return dict(talent_id=1,start_date='2027-01-04',end_date='2027-01-05',start_time='09:00:00',end_time='17:00:00',site_name='Site',site_address='London',contact_name='Test',contact_phone='07000000000')

def test_profile(context):
    c,s,*_=context
    assert c.post('/companies/',json={'name':'Test'}).status_code==200
    r=c.patch('/companies/me',json={'postcode':'SW1A 1AA','industry':'Engineering'})
    assert r.status_code==200 and r.json()['postcode']=='SW1A 1AA'

def test_job_permissions_and_archive(context):
    c,s,active,pro,co=context
    job=c.post('/jobs/',json={'title':'Test','description':'Test'}).json()
    active[0]=pro
    assert c.post('/jobs/',json={'title':'Forbidden','description':'Test'}).status_code==403
    active[0]=User(id=3,role='company',email='other@example.com')
    assert c.patch(f'/jobs/{job["id"]}',json={'title':'Hijack'}).status_code==404
    active[0]=co;assert c.delete(f'/jobs/{job["id"]}').status_code==204
    active[0]=pro;assert c.post(f'/jobs/{job["id"]}/apply',json={}).status_code==409
    assert not s.exec(select(TalentApplication)).all()

def test_overlap_duplicate_and_adjacent(context):
    c,s,active,pro,co=context
    for start,end,expected in [('09:00:00','12:00:00',200),('12:00:00','17:00:00',200),('10:00:00','14:00:00',409)]:
        active[0]=co;body=payload();body.update(start_time=start,end_time=end)
        req=c.post('/company/booking-requests',json=body).json();active[0]=pro
        assert c.post(f'/professional/booking-requests/{req["id"]}/accept').status_code==expected
        if expected==200:assert c.post(f'/professional/booking-requests/{req["id"]}/accept').status_code==400
    assert len(s.exec(select(Booking)).all())==2

@pytest.mark.parametrize('field,value',[('end_date','2026-01-01'),('end_time','08:00:00')])
def test_invalid_dates(context,field,value):
    c,*_=context;body=payload();body[field]=value
    assert c.post('/company/booking-requests',json=body).status_code==422

def test_application_transitions(context):
    c,s,active,pro,co=context
    job=c.post('/jobs/',json={'title':'Engineer','description':'Test'}).json();active[0]=pro
    a=c.post(f'/jobs/{job["id"]}/apply',json={}).json()
    assert c.patch(f'/applications/{a["id"]}',json={'status':'shortlisted'}).status_code==409
    active[0]=co;assert c.patch(f'/applications/{a["id"]}',json={'status':'shortlisted'}).status_code==200
    active[0]=pro;assert c.patch(f'/applications/{a["id"]}',json={'status':'withdrawn'}).status_code==200

def test_uploads(context,monkeypatch):
    c,s,active,pro,co=context;stored=[]
    class Storage:
        def put_object(self,**kwargs):stored.append(kwargs)
        def generate_presigned_url(self,*args,**kwargs):return 'https://private.example.com/cv?signature=temporary'
    monkeypatch.setattr(uploads,'r2_client',lambda:Storage())
    monkeypatch.setattr(uploads,'bucket_name',lambda:'images')
    monkeypatch.setattr(uploads,'public_base_url',lambda:'https://images.example.com')
    c.post('/companies/',json={'name':'Test'})
    r=c.post('/uploads/company-logo',files={'file':('logo.png',b'\x89PNG\r\n\x1a\nexample','image/png')})
    assert r.status_code==200 and s.exec(select(Company)).one().logo_url==r.json()['url']
    active[0]=pro
    assert c.post('/uploads/avatar',files={'file':('photo.png',b'<script>bad</script>','image/png')}).status_code==400
    monkeypatch.delenv('R2_PRIVATE_BUCKET_NAME',raising=False)
    assert c.post('/uploads/cv',files={'file':('cv.pdf',b'%PDF-example','application/pdf')}).status_code==503
    monkeypatch.setenv('R2_PRIVATE_BUCKET_NAME','private-cvs')
    r=c.post('/uploads/cv',files={'file':('cv.pdf',b'%PDF-example','application/pdf')})
    assert r.status_code==200 and r.json()['url']=='/api/uploads/cv/1'
    assert stored[-1]['Bucket']=='private-cvs'
    assert c.get('/uploads/cv/1',follow_redirects=False).status_code==307
    active[0]=User(id=99,email='unrelated@example.com',role='professional')
    assert c.get('/uploads/cv/1',follow_redirects=False).status_code==403
    active[0]=co;assert c.get('/uploads/cv/1',follow_redirects=False).status_code==307

def test_migration_repeatable():
    from sqlalchemy import text,inspect
    from scripts.prepare_launch import migrate
    engine=create_engine('sqlite://')
    with engine.begin() as c:c.execute(text('CREATE TABLE company (id INTEGER PRIMARY KEY, name VARCHAR)'))
    migrate(engine);migrate(engine)
    assert {'postcode','industry','logo_url','updated_at'}.issubset({x['name'] for x in inspect(engine).get_columns('company')})
    engine.dispose()

def test_recurrence_keeps_london_wall_clock_across_dst():
    from app.routers.availability import _generate_occurrences
    from models.availability import Availability
    from datetime import datetime, timezone
    block=Availability(user_id=1,start_at=datetime(2027,3,27,9),end_at=datetime(2027,3,27,10),status='busy',timezone='Europe/London',rrule='FREQ=DAILY;COUNT=3')
    occurrences=list(_generate_occurrences(block,datetime(2027,3,26,tzinfo=timezone.utc),datetime(2027,3,31,tzinfo=timezone.utc)))
    assert [start.hour for start,end in occurrences]==[9,8,8]
    assert all((end-start).total_seconds()==3600 for start,end in occurrences)

def test_recurring_block_started_before_window_still_overlaps():
    from app.routers.availability import _generate_occurrences
    from models.availability import Availability
    from datetime import datetime
    block=Availability(user_id=1,start_at=datetime(2027,1,1,9),end_at=datetime(2027,1,1,12),status='busy',rrule='FREQ=DAILY;COUNT=5')
    assert len(list(_generate_occurrences(block,datetime(2027,1,3,10),datetime(2027,1,3,11))))==1

def test_shared_rate_limit():
    from app.rate_limits import RequestWindow, consume
    engine=create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        assert consume(s,'test-identity',2)
        assert consume(s,'test-identity',2)
        assert not consume(s,'test-identity',2)
        assert consume(s,'other-identity',2)
    engine.dispose()


def test_notification_failure_is_retryable(context,monkeypatch):
    from app import notifications
    from datetime import datetime,timedelta
    c,s,active,pro,co=context
    notifications.enqueue(s,'test-event',co.id,'Test','Test','/dashboard/company');s.commit()
    def fail(*args):raise RuntimeError('test mail failure')
    monkeypatch.setattr(notifications,'send_email',fail)
    assert notifications.deliver_pending(s)['failed']==1
    item=s.exec(select(notifications.EmailNotification)).one()
    assert item.sent_at is None and item.attempts==1
    item.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);s.add(item);s.commit()
    monkeypatch.setattr(notifications,'send_email',lambda *args:None)
    assert notifications.deliver_pending(s)['sent']==1
    assert notifications.deliver_pending(s)['sent']==0
