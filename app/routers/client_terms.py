from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from app.db import get_session
from auth.deps import require_admin
from auth.models import User
from models.company import Company
from models.client_terms import ClientPaymentTerms, ClientPaymentTermsAudit
router = APIRouter(prefix='/admin/client-payment-terms', tags=['admin'])

class TermsUpdate(BaseModel):
    payment_due_days: int = Field(ge=0, le=365, strict=True)
    expected_revision: int = Field(ge=0, strict=True)

def terms_for(session, user_id):
    row=session.get(ClientPaymentTerms,user_id)
    return {'payment_due_days':row.payment_due_days if row else 7,'revision':row.revision if row else 0}

@router.get('')
def list_terms(admin: User=Depends(require_admin),session: Session=Depends(get_session)):
    users=session.exec(select(User).where(User.role=='company')).all()
    profiles={c.owner_id:c.name for c in session.exec(select(Company)).all()}
    return [{'user_id':u.id,'name':profiles.get(u.id,u.email),'email':u.email,**terms_for(session,u.id)} for u in users]

@router.patch('/{user_id}')
def update_terms(user_id:int,body:TermsUpdate,admin:User=Depends(require_admin),session:Session=Depends(get_session)):
    user=session.exec(select(User).where(User.id==user_id).with_for_update()).first()
    if not user or user.role!='company':raise HTTPException(404,'Client not found')
    current=terms_for(session,user_id)
    if body.expected_revision!=current['revision']:raise HTTPException(409,'Another admin updated these terms. Reload before saving.')
    row=session.get(ClientPaymentTerms,user_id) or ClientPaymentTerms(user_id=user_id,updated_by=admin.id)
    row.payment_due_days=body.payment_due_days;row.revision=current['revision']+1
    row.updated_by=admin.id;row.updated_at=datetime.utcnow()
    session.add(row);session.add(ClientPaymentTermsAudit(user_id=user_id,payment_due_days=row.payment_due_days,revision=row.revision,changed_by=admin.id))
    session.commit()
    return terms_for(session,user_id)
