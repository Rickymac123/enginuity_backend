import pytest
from fastapi import HTTPException
from app.uk_eligibility import uk_postcode,uk_site_address
from tests.test_launch_repairs import context,payload
from tests.test_billing import ctx,configured
from tests.test_agency_assurance import agency_context
from models.company import Company
from sqlmodel import select

@pytest.mark.parametrize('value',['CF48 3PN','sw1a1aa','BT1 1AA','EH1 1AA','GIR 0AA'])
def test_uk_postcodes(value):
    assert uk_postcode(value)
@pytest.mark.parametrize('value',['','75001','10001','D02 X285','JE2 3AA','GY1 1AA','IM1 1AA','AI-2640',None])
def test_non_uk_or_missing_postcode_rejected(value):
    with pytest.raises(HTTPException):uk_postcode(value)

def test_site_address_requires_uk_postcode():
    assert uk_site_address('High Street, Merthyr Tydfil CF48 3PN')=='CF48 3PN'
    for value in ['Paris 75001','Jersey JE2 3AA','', 'wordSW1A1AAword']:
        with pytest.raises(HTTPException):uk_site_address(value)

def test_job_create_and_edit_enforce_uk(context):
    c,s,a,co,pro=context
    assert c.post('/jobs/',json={'title':'Test','description':'Test','postcode':'75001'}).status_code==422
    r=c.post('/jobs/',json={'title':'Test','description':'Test','postcode':'bt11aa'})
    assert r.status_code==200 and r.json()['postcode']=='BT1 1AA'
    assert c.patch('/jobs/'+str(r.json()['id']),json={'postcode':'JE2 3AA'}).status_code==422
    assert c.patch('/jobs/'+str(r.json()['id']),json={'title':'Updated'}).status_code==200

def test_direct_booking_rejects_non_uk_site(context):
    c,*_=context;body=payload();body['site_address']='Paris 75001'
    assert c.post('/company/booking-requests',json=body).status_code==422

def test_membership_requires_uk_business_not_uk_card(ctx,monkeypatch):
    c,s,a,u=ctx;configured(monkeypatch)
    profile=s.exec(select(Company).where(Company.owner_id==1)).one()
    profile.postcode='75001';s.add(profile);s.commit()
    assert c.post('/billing/checkout',json={'interval':'month','uk_business':True,'terms_accepted':True}).status_code==422
    assert c.post('/billing/redeem',json={'code':'FOUNDERS100','uk_business':True}).status_code==422
    profile.postcode='CF48 3PN';s.add(profile);s.commit()
    assert c.post('/billing/redeem',json={'code':'FOUNDERS100'}).status_code==422
    assert c.post('/billing/redeem',json={'code':'FOUNDERS100','uk_business':True}).status_code==200
