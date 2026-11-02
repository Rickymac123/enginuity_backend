from datetime import date, time, datetime
from sqlalchemy.dialects import postgresql
from sqlmodel import Session, SQLModel, create_engine, select
from models.talent import Talent
from models.jobpost import JobPost
from models.booking import Booking
from models.availability import Availability
from auth.models import User
from app.routers.company_matches import _score_match, _available_for_job, _experience_matches
from app.routers.jobs import _contains_if_present

def talent(**kw):
 return Talent(id=1,user_id=1,first_name='Test',last_name='Pro',profession_category='engineering',profession='Engineer',location='Cardiff',**kw)
def job(**kw):
 return JobPost(id=1,company_id=2,title='Engineer',description='Test',**kw)

def test_score_uses_only_supplied_criteria_and_stays_within_percentage():
 score,reasons=_score_match(job(profession='engineer'),talent())
 assert score==100 and reasons==['Profession match']
 assert _score_match(job(),talent())[0]==0
 assert _score_match(job(experience_level='senior'),talent())[0]==0
 assert not _experience_matches(job(experience_level='senior'),talent())

def test_comma_and_newline_skills_are_equivalent():
 assert _score_match(job(required_skills='PLC, welding'),talent(skills='plc\nWELDING'))[0]==100
 assert _score_match(job(required_skills='PLC, welding'),talent(skills='PLC'))[0]==50

def test_ir35_either_and_missing_are_not_confused():
 assert _score_match(job(ir35_type='either'),talent(ir35_preference='outside'))[0]==100
 assert _score_match(job(ir35_type='inside'),talent())[0]==0

def test_search_is_case_insensitive_and_treats_wildcards_literally():
 engine=create_engine('sqlite://');SQLModel.metadata.create_all(engine)
 with Session(engine) as s:
  s.add_all([job(location='Cardiff'),JobPost(id=2,company_id=2,title='Other',description='Test',location='100% remote')]);s.commit()
  statement=_contains_if_present(select(JobPost),JobPost.location,'CARDIFF')
  assert [j.id for j in s.exec(statement)]==[1]
  assert [j.id for j in s.exec(_contains_if_present(select(JobPost),JobPost.location,'%'))]==[2]
  sql=str(statement.compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
  assert 'lower(jobpost.location)' in sql and "'cardiff'" in sql
 engine.dispose()

def test_matching_respects_shift_times_busy_calendar_and_cancelled_bookings():
 engine=create_engine('sqlite://');SQLModel.metadata.create_all(engine)
 with Session(engine) as s:
  p=talent();j=job(start_date=date(2027,1,4),end_date=date(2027,1,4),start_time=time(12),end_time=time(17))
  s.add_all([User(id=1,email='test@example.com',hashed_password='unused'),p]);s.commit()
  booking=Booking(booking_request_id=1,company_id=2,talent_id=1,start_date=j.start_date,end_date=j.end_date,start_time=time(9),end_time=time(12),site_name='Test',site_address='Test',contact_name='Test',contact_phone='000')
  s.add(booking);s.commit()
  assert _available_for_job(s,j,p)
  booking.end_time=time(13);s.add(booking);s.commit()
  assert not _available_for_job(s,j,p)
  booking.status='cancelled';s.add(booking);s.commit()
  assert _available_for_job(s,j,p)
  s.add(Availability(user_id=1,start_at=datetime(2027,1,4,13),end_at=datetime(2027,1,4,14),status='busy',timezone='Europe/London'));s.commit()
  assert not _available_for_job(s,j,p)
 engine.dispose()
