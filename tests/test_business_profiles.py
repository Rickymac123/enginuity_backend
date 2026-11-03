from tests.test_agency_assurance import agency_context
from app.routers import companies
from models.company import Company
from models.jobpost import JobPost

def test_public_profile_opt_in_and_private_fields(agency_context):
 c,s,active,users=agency_context;c.app.include_router(companies.router)
 active[0]=users[1]
 r=c.post('/companies/',json={'name':'Example Business','postcode':'PRIVATE','description':'Public description'})
 assert r.status_code==200
 assert c.get('/businesses/2').status_code==404
 assert c.patch('/companies/me',json={'is_public':True,'website':'javascript:alert(1)'}).status_code==200
 s.add(JobPost(company_id=2,title='Open job',description='private site details',site_address='SECRET'))
 s.add(JobPost(company_id=2,title='Closed job',description='old',is_archived=True));s.commit()
 data=c.get('/businesses/2').json()
 assert data['name']=='Example Business' and data['website'] is None
 assert [j['title'] for j in data['jobs']]==['Open job']
 assert 'PRIVATE' not in str(data) and 'SECRET' not in str(data) and 'email' not in data and 'owner_id' not in data
 active[0]=users[2]
 assert c.patch('/companies/me',json={'name':'Stolen'}).status_code==404
 active[0]=users[1];assert c.patch('/companies/me',json={'is_public':False}).status_code==200
 assert c.get('/businesses/2').status_code==404

def test_agency_profile_and_inactive_owner(agency_context):
 c,s,active,users=agency_context;c.app.include_router(companies.router)
 assert c.post('/companies/',json={'name':'Agency','is_public':True,'website':'https://example.com'}).status_code==200
 assert c.get('/businesses/1').json()['account_type']=='agency'
 users[0].is_active=False;s.add(users[0]);s.commit()
 assert c.get('/businesses/1').status_code==404

def test_existing_company_migration_defaults_private():
 from sqlalchemy import text
 from sqlmodel import create_engine
 from scripts.prepare_launch import migrate
 e=create_engine('sqlite://')
 with e.begin() as c:
  c.execute(text('CREATE TABLE company (id INTEGER PRIMARY KEY)'))
  c.execute(text('INSERT INTO company (id) VALUES (1)'))
 migrate(e);migrate(e)
 with e.connect() as c: assert c.execute(text('SELECT is_public FROM company WHERE id=1')).scalar()==0
