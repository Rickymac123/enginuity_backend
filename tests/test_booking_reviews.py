from datetime import date, datetime, timedelta, time
import pytest
from sqlmodel import select
from tests.test_launch_repairs import context
from tests.test_booking_cancellation import accepted
from models.booking import Booking
from models.review import Review
from app.notifications import EmailNotification, deliver_pending
from auth.models import User

COMMENT='The professional delivered the agreed work carefully and communicated clearly throughout the booking.'

def setup(context):
    c,s,active,pro,co=context
    rid=accepted(context);active[0]=co
    b=s.exec(select(Booking)).one();b.end_date=date.today()-timedelta(days=1);s.add(b);s.commit()
    return rid,b


def test_completion_review_and_duplicate(context):
    c,s,active,pro,co=context;rid,b=setup(context);base=f'/bookings/by-request/{rid}'
    assert c.post(base+'/review',json={'rating':5,'comment':COMMENT}).status_code==409
    assert c.post(base+'/complete').status_code==200
    assert c.post(base+'/complete').status_code==200
    assert c.get('/company/booking-requests').json()[0]['status']=='completed'
    assert c.post(base+'/review',json={'rating':6,'comment':COMMENT}).status_code==422
    assert c.post(base+'/review',json={'rating':5,'comment':' '*60}).status_code==422
    assert c.post(base+'/review',json={'rating':5,'comment':COMMENT}).status_code==201
    assert c.post(base+'/review',json={'rating':1,'comment':COMMENT}).status_code==409
    assert c.get(base+'/review').json()['reviewed'] is True
    review=s.exec(select(Review)).one()
    assert review.professional_id==pro.id and review.company_id==co.id and review.source=='platform'
    assert len(s.exec(select(EmailNotification).where(EmailNotification.event_key.like('booking-review-invite:%'))).all())==1

@pytest.mark.parametrize('role',['professional','company','agency','admin'])
def test_non_owner_cannot_complete_or_review(context,role):
    c,s,active,pro,co=context;rid,b=setup(context)
    active[0]=User(id=99,email='other@example.com',role=role,is_verified=True,is_active=True)
    base=f'/bookings/by-request/{rid}'
    assert c.get(base+'/review').status_code==404
    assert c.post(base+'/complete').status_code==404
    assert c.post(base+'/review',json={'rating':5,'comment':COMMENT}).status_code==404


def test_future_cancelled_cannot_complete(context):
    c,s,active,pro,co=context;rid,b=setup(context);base=f'/bookings/by-request/{rid}'
    b.end_date=date.today()+timedelta(days=2);s.add(b);s.commit()
    assert c.get(base+'/review').json()['can_complete'] is False
    assert c.post(base+'/complete').status_code==409
    b.status='cancelled';s.add(b);s.commit()
    assert c.post(base+'/complete').status_code==409


def test_one_reminder_and_suppress_after_review(context,monkeypatch):
    from app import notifications
    c,s,active,pro,co=context;rid,b=setup(context)
    c.post(f'/bookings/by-request/{rid}/complete')
    sent=[];monkeypatch.setattr(notifications,'send_email',lambda *args:sent.append(args))
    deliver_pending(s)
    invite=s.exec(select(EmailNotification).where(EmailNotification.event_key==f'booking-review-invite:{b.id}')).one()
    invite.sent_at=datetime.utcnow()-timedelta(days=8);s.add(invite);s.commit()
    deliver_pending(s);deliver_pending(s)
    assert sum('reminder to review' in x[1] for x in sent)==1
    reminder=s.exec(select(EmailNotification).where(EmailNotification.event_key==f'booking-review-reminder:{b.id}')).one()
    reminder.sent_at=None;reminder.attempts=0;s.add(reminder);s.commit()
    c.post(f'/bookings/by-request/{rid}/review',json={'rating':4,'comment':COMMENT})
    deliver_pending(s)
    assert sum('reminder to review' in x[1] for x in sent)==1
    s.refresh(reminder);assert reminder.attempts==10


def test_migration_additive_repeatable():
    from sqlalchemy import create_engine, text, inspect
    from scripts.prepare_launch import migrate
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE booking (id INTEGER PRIMARY KEY, booking_request_id INTEGER)'))
        c.execute(text('CREATE TABLE review (id INTEGER PRIMARY KEY, comment VARCHAR)'))
        c.execute(text("INSERT INTO review (id, comment) VALUES (1, 'existing review')"))
    migrate(engine);migrate(engine)
    assert 'booking_id' in {x['name'] for x in inspect(engine).get_columns('review')}
    with engine.begin() as c:
        assert c.execute(text('SELECT comment FROM review WHERE id=1')).scalar()=='existing review'
    engine.dispose()
