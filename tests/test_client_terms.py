from sqlmodel import select
from tests.test_agency_assurance import agency_context, person
from tests.test_launch_repairs import payload
from app.routers import client_terms
from auth.models import User
from models.client_terms import ClientPaymentTermsAudit
from models.booking import Booking

def test_admin_only_validated_terms_audit_and_booking_snapshot(agency_context):
 c,s,active,users=agency_context;c.app.include_router(client_terms.router)
 assert c.get('/admin/client-payment-terms').status_code==403
 admin=User(id=90,email='admin@example.com',hashed_password='unused',role='admin',is_superuser=True,is_active=True,is_verified=True);s.add(admin);s.commit()
 active[0]=admin
 assert c.get('/admin/client-payment-terms').json()[0]['payment_due_days']==7
 for days in [-1,366,1.5,True,'7']:
  assert c.patch('/admin/client-payment-terms/2',json={'payment_due_days':days,'expected_revision':0}).status_code==422
 assert c.patch('/admin/client-payment-terms/1',json={'payment_due_days':14,'expected_revision':0}).status_code==404
 assert c.patch('/admin/client-payment-terms/2',json={'payment_due_days':14,'expected_revision':0}).json()=={'payment_due_days':14,'revision':1}
 assert c.patch('/admin/client-payment-terms/2',json={'payment_due_days':30,'expected_revision':0}).status_code==409
 active[0]=users[0];talent=c.post('/talent/',json=person()).json()
 active[0]=users[1];body=payload();body['talent_id']=talent['id']
 req=c.post('/company/booking-requests',json=body);assert req.status_code==200,req.text
 assert req.json()['client_payment_due_days']==14
 active[0]=admin
 assert c.patch('/admin/client-payment-terms/2',json={'payment_due_days':30,'expected_revision':1}).status_code==200
 active[0]=users[0];assert c.post(f'/agency/booking-requests/{req.json()["id"]}/accept').status_code==200
 booking=s.exec(select(Booking)).one();assert booking.client_payment_due_days==14 and booking.client_terms_revision==1
 audit=s.exec(select(ClientPaymentTermsAudit)).all();assert [x.payment_due_days for x in audit]==[14,30]
 assert all(x.changed_by==90 for x in audit)
