import json
from datetime import datetime,date,time,timedelta
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel,Session,create_engine,select
from auth.models import User
from auth.deps import current_user,require_admin
from app.db import get_session
from app.routers import work_billing
from app.work_billing import charge
from models.booking import Booking
from models.talent import Talent
from models.work_billing import *

@pytest.fixture
def context(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        users=[User(id=i,email=f'{i}@example.test',hashed_password='unused',role=r,is_active=True,is_verified=True,is_superuser=r=='admin') for i,r in [(1,'professional'),(2,'company'),(3,'company'),(4,'admin'),(5,'agency')]]
        s.add_all(users);s.add(WorkBillingSettings());s.add(Talent(id=1,user_id=1,first_name='Test',last_name='Person',profession='Engineer',profession_category='engineering',location='UK'))
        s.add(Booking(id=1,booking_request_id=1,company_id=2,talent_id=1,start_date=date(2026,1,1),end_date=date(2026,1,31),start_time=time(8),end_time=time(17),site_name='Test',site_address='UK',contact_name='Test',contact_phone='0',client_payment_due_days=7));s.commit()
        active=[users[0]];app=FastAPI();app.include_router(work_billing.router)
        app.dependency_overrides[get_session]=lambda:s
        app.dependency_overrides[current_user]=lambda:active[0]
        # Keep the production role check active via overridden current_user.
        yield TestClient(app),s,active,users

def rate(c):return c.put('/work-billing/bookings/1/rate',json=dict(contractor_pence=4000,markup_bps=2000,unit='hour',day_minutes=480,expected_revision=0))
def sheet():return dict(week_start='2026-01-05',expected_revision=0,entries=[dict(start='2026-01-05T08:00:00+00:00',end='2026-01-05T17:00:00+00:00',break_minutes=60)])

def test_markup_rounding():
    assert charge(480,4000,2000)==(4800,38400)
    assert charge(240,32000,2000,'day',480)==(38400,19200)
    assert charge(1,1,2000)==(1,0)

def test_rates_roles_submission_correction_and_approval(context,monkeypatch):
    c,s,a,u=context
    assert rate(c).status_code==403
    a[0]=u[3];assert rate(c).status_code==200
    assert c.patch('/work-billing/settings',json={'markup_bps':2500,'expected_revision':0}).status_code==200
    assert c.patch('/work-billing/settings',json={'markup_bps':3000,'expected_revision':0}).status_code==409
    a[0]=u[0];r=c.post('/work-billing/bookings/1/timesheets',json=sheet());assert r.status_code==200,r.text
    sid=r.json()['id'];assert 'net_pence' not in r.json()
    assert c.post('/work-billing/bookings/1/timesheets',json=sheet()).status_code==409
    a[0]=u[2];assert not c.get('/work-billing').json()['bookings']
    assert c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':1}).status_code==404
    a[0]=u[1];v=c.get('/work-billing').json()['bookings'][0];assert v['rate']['client_rate_pence']==4800
    assert 'contractor_pence' not in v['rate'] and 'markup_bps' not in v['timesheets'][0]
    assert c.post(f'/work-billing/timesheets/{sid}/return',json={'expected_revision':1,'reason':'Correct break'}).status_code==200
    a[0]=u[0];body=sheet();body['expected_revision']=2;assert c.post('/work-billing/bookings/1/timesheets',json=body).status_code==200
    monkeypatch.setenv('WORK_INVOICING_ENABLED','true')
    a[0]=u[1];assert c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':3}).status_code==409
    import app.quickbooks_work as q
    monkeypatch.setattr(q,'configured',lambda s:True);monkeypatch.setattr(q,'process_pending',lambda *a,**k:None)
    monkeypatch.setenv('QBO_SERVICE_ITEM_ID','1');monkeypatch.setenv('QBO_SALES_TAX_CODE_ID','2')
    s.add(QuickBooksClient(company_id=2,customer_id='10',invoice_email='client@example.test'));s.commit()
    r=c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':3});assert r.status_code==200,r.text
    assert r.json()['invoice']['net_pence']==38400 and r.json()['invoice']['vat_pence']==7680
    assert c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':3}).status_code==200
    invoices=s.exec(select(WorkInvoice)).all();assert len(invoices)==1
    assert invoices[0].due_date-invoices[0].issue_date==timedelta(days=7)
    a[0]=u[3];assert rate(c).status_code==409

@pytest.mark.parametrize('change',[
 {'entries':[dict(start='2026-01-05T08:00+00:00',end='2026-01-05T09:00+00:00',break_minutes=60)]},
 {'week_start':'2026-01-06'},
 {'entries':[dict(start='2026-02-05T08:00+00:00',end='2026-02-05T09:00+00:00',break_minutes=0)]},
 {'entries':[dict(start='2026-01-05T08:00+00:00',end='2026-01-05T09:00+00:00',break_minutes=0)]*2},
])
def test_invalid_time_entries(context,change):
    c,s,a,u=context;a[0]=u[3];assert rate(c).status_code==200;a[0]=u[0]
    body=sheet();body.update(change);assert c.post('/work-billing/bookings/1/timesheets',json=body).status_code==422

def test_overnight_and_overlap(context):
    c,s,a,u=context;a[0]=u[3];rate(c);a[0]=u[0]
    body=sheet();body['entries']=[dict(start='2026-01-11T22:00+00:00',end='2026-01-12T06:00+00:00',break_minutes=30)]
    assert c.post('/work-billing/bookings/1/timesheets',json=body).json()['total_minutes']==450
    body.update(week_start='2026-01-12',entries=[dict(start='2026-01-12T05:00+00:00',end='2026-01-12T08:00+00:00',break_minutes=0)])
    assert c.post('/work-billing/bookings/1/timesheets',json=body).status_code==409

def test_local_uk_times_are_normalised(context):
    c,s,a,u=context;a[0]=u[3];rate(c);a[0]=u[0]
    body=sheet();body['entries'][0].update(start='2026-01-05T08:00',end='2026-01-05T17:00')
    result=c.post('/work-billing/bookings/1/timesheets',json=body)
    assert result.status_code==200 and result.json()['entries'][0]['start'].endswith(('Z','+00:00'))

def test_qbo_create_send_and_duplicate_worker(context,monkeypatch):
    from app import quickbooks_work as q
    c,s,a,u=context
    monkeypatch.setattr(q,'configured',lambda s:True)
    payload={'DocNumber':'CP-TS-1','CustomerRef':{'value':'10'},'BillEmail':{'Address':'test@example.test'}}
    row=WorkInvoice(timesheet_id=1,company_id=2,issue_date=date(2026,1,12),due_date=date(2026,1,19),net_pence=38400,vat_pence=7680,payload_json=json.dumps(payload));s.add(row);s.commit()
    calls=[]
    invoice={'Id':'91','DocNumber':'CP-TS-1','CustomerRef':{'value':'10'},'CurrencyRef':{'value':'GBP'},'TotalAmt':460.8,'DueDate':'2026-01-19','Balance':460.8,'EmailStatus':'NotSet'}
    class Fake:
        def __init__(self,session):pass
        def token(self):return 'realm','token'
        def request(self,method,path,payload=None,params=None):
            calls.append((method,path,params))
            if path=='query':return {'QueryResponse':{}}
            if path.endswith('/send'):invoice['EmailStatus']='EmailSent'
            return {'Invoice':invoice.copy()}
    monkeypatch.setattr(q,'QBO',Fake)
    q.process_pending(s);q.process_pending(s)
    s.refresh(row);assert row.status=='sent' and row.provider_id=='91'
    assert sum(m=='POST' and p=='invoice' for m,p,_ in calls)==1
    assert sum(p.endswith('/send') for _,p,_ in calls)==1

def test_ambiguous_provider_failure_never_recreates(context,monkeypatch):
    from app import quickbooks_work as q
    c,s,a,u=context;monkeypatch.setattr(q,'configured',lambda s:True)
    row=WorkInvoice(timesheet_id=1,company_id=2,issue_date=date(2026,1,12),due_date=date(2026,1,19),net_pence=100,vat_pence=20,payload_json=json.dumps({'DocNumber':'CP-TS-1','CustomerRef':{'value':'10'}}));s.add(row);s.commit();writes=[]
    class Fake:
        def __init__(self,session):pass
        def token(self):return 'realm','token'
        def request(self,method,path,payload=None,params=None):
            if path=='query':return {'QueryResponse':{}}
            writes.append(path);raise TimeoutError('provider response lost')
    monkeypatch.setattr(q,'QBO',Fake);q.process_pending(s);q.process_pending(s)
    s.refresh(row);assert row.status=='reconciliation_required' and writes==['invoice']

def test_wrong_provider_total_is_not_sent(context,monkeypatch):
    from app import quickbooks_work as q
    c,s,a,u=context;monkeypatch.setattr(q,'configured',lambda s:True)
    row=WorkInvoice(timesheet_id=1,company_id=2,issue_date=date(2026,1,12),due_date=date(2026,1,19),net_pence=100,vat_pence=20,payload_json=json.dumps({'DocNumber':'CP-TS-1','CustomerRef':{'value':'10'}}));s.add(row);s.commit();calls=[]
    class Fake:
        def __init__(self,session):pass
        def token(self):return 'realm','token'
        def request(self,method,path,payload=None,params=None):
            calls.append(path)
            if path=='query':return {'QueryResponse':{}}
            return {'Invoice':{'Id':'91','DocNumber':'CP-TS-1','CustomerRef':{'value':'10'},'CurrencyRef':{'value':'GBP'},'TotalAmt':999,'DueDate':'2026-01-19'}}
    monkeypatch.setattr(q,'QBO',Fake);q.process_pending(s);s.refresh(row)
    assert row.status=='reconciliation_required' and not any(p.endswith('/send') for p in calls)

def test_qbo_send_uses_binary_content_type(monkeypatch):
    from app.quickbooks_work import QBO
    import httpx
    calls=[]
    monkeypatch.setattr(QBO,'token',lambda self:('sandbox-company','test-token'))
    monkeypatch.setenv('QBO_ENVIRONMENT','sandbox')
    def request(method,url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={'Invoice':{'EmailStatus':'EmailSent'}})
    monkeypatch.setattr(httpx,'request',request)
    QBO(None).request('POST','invoice/123/send',params={'sendTo':'test@example.test'})
    assert calls[0][0].startswith('https://sandbox-quickbooks.api.intuit.com/')
    assert calls[0][1]['headers']['Content-Type']=='application/octet-stream'
    assert calls[0][1]['json'] is None


def test_approval_with_issuing_off_never_queues_or_calls_provider(context,monkeypatch):
    c,s,a,u=context
    monkeypatch.setenv('WORK_INVOICING_ENABLED','false')
    import app.quickbooks_work as q
    def forbidden(*args,**kwargs):raise AssertionError('Provider must not be called')
    monkeypatch.setattr(q,'process_pending',forbidden)
    a[0]=u[3];assert rate(c).status_code==200
    a[0]=u[0];sid=c.post('/work-billing/bookings/1/timesheets',json=sheet()).json()['id']
    a[0]=u[1]
    r=c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':1})
    assert r.status_code==200 and r.json()['status']=='approved'
    assert not s.exec(select(WorkInvoice)).all()
    monkeypatch.setenv('WORK_INVOICING_ENABLED','true')
    assert c.post(f'/work-billing/timesheets/{sid}/approve',json={'expected_revision':1}).status_code==200
    assert not s.exec(select(WorkInvoice)).all()
    assert s.exec(select(WorkAudit).where(WorkAudit.action=='invoice_held')).first()
