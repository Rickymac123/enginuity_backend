import pytest
from sqlmodel import select
from tests.test_launch_repairs import context, payload
from auth.models import User
from models.booking import Booking
from models.talent import Talent
from app.notifications import EmailNotification


def accepted(context):
    c,s,active,pro,co=context
    req=c.post('/company/booking-requests',json=payload()).json()
    active[0]=pro
    assert c.post(f'/professional/booking-requests/{req["id"]}/accept').status_code==200
    return req['id']

@pytest.mark.parametrize('role',['company','professional','agency'])
def test_participant_cancel_and_repeat(context,role):
    c,s,active,pro,co=context;rid=accepted(context)
    if role=='agency':
        agency=User(id=3,email='agency@example.com',role='agency',is_active=True,is_verified=True,hashed_password='unused');s.add(agency)
        talent=s.get(Talent,1);talent.user_id=None;talent.agency_id=3;s.add(talent);s.commit();active[0]=agency
    else:active[0]=co if role=='company' else pro
    url=f'/bookings/by-request/{rid}/cancel'
    assert c.post(url,json={'reason':'  '}).status_code==422
    result=c.post(url,json={'reason':'Test finished'})
    assert result.status_code==200 and result.json()['status']=='cancelled'
    assert 'Test finished' in result.json()['notes']
    assert c.post(url,json={'reason':'Second attempt'}).json()['notes']==result.json()['notes']
    events=s.exec(select(EmailNotification).where(EmailNotification.event_key.like('confirmed-booking-cancelled:%'))).all()
    assert len(events)==1 and events[0].recipient_id==(1 if role=='company' else 2)
    active[0]=co
    requests=c.get('/company/booking-requests').json()
    assert requests[0]['status']=='cancelled'
    if role!='agency':
        req=c.post('/company/booking-requests',json=payload()).json();active[0]=pro
        assert c.post(f'/professional/booking-requests/{req["id"]}/accept').status_code==200

@pytest.mark.parametrize('role',['company','professional','agency','admin'])
def test_unrelated_cannot_cancel(context,role):
    c,s,active,pro,co=context;rid=accepted(context)
    active[0]=User(id=99,email='other@example.com',role=role,is_active=True,is_verified=True)
    assert c.post(f'/bookings/by-request/{rid}/cancel',json={'reason':'Not mine'}).status_code==404
    assert s.exec(select(Booking)).one().status=='confirmed'


def test_completed_booking_cannot_cancel(context):
    c,s,active,pro,co=context;rid=accepted(context)
    booking=s.exec(select(Booking)).one();booking.status='completed';s.add(booking);s.commit()
    assert c.post(f'/bookings/by-request/{rid}/cancel',json={'reason':'Wrong state'}).status_code==409
