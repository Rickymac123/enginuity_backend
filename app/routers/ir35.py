import json
from datetime import datetime
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from auth.models import User
from auth.deps import current_user
from app.db import get_session
from app.work_billing import authorised_booking
from app.storage.r2 import r2_client, private_bucket_name
from app.ir35 import VERSION, NOTICE, CEST, SOURCE, QUESTIONS, catalogue, guidance
from models.booking import Booking
from models.ir35 import IR35Record, IR35History, IR35Attachment

def private_response(response: Response):
    response.headers['Cache-Control']='private, no-store'

router=APIRouter(prefix='/ir35',tags=['IR35 guidance'],dependencies=[Depends(private_response)])
MAX_BYTES=4*1024*1024
class Answers(BaseModel):
    expected_revision: int = Field(ge=0,strict=True)
    answers: dict[str,Literal['yes','no','unknown']] = Field(max_length=20)
    notes: str = Field(default='',max_length=5000)


def access(session,user,rid):
    booking=session.exec(select(Booking).where(Booking.booking_request_id==rid)).first()
    if not booking:raise HTTPException(404,'Confirmed booking not found')
    return authorised_booking(session,user,booking.id)

def view(session,booking,role):
    row=session.get(IR35Record,booking.id)
    answers=json.loads(row.answers_json) if row else {}
    files=session.exec(select(IR35Attachment).where(IR35Attachment.booking_id==booking.id).order_by(IR35Attachment.id.desc())).all()
    history=session.exec(select(IR35History).where(IR35History.booking_id==booking.id).order_by(IR35History.revision.desc())).all()
    return dict(booking=dict(id=booking.id,request_id=booking.booking_request_id,site_name=booking.site_name,start_date=booking.start_date,end_date=booking.end_date,status=booking.status),role=role,
        notice=NOTICE,version=VERSION,cest_url=CEST,source_url=SOURCE,questions=catalogue(),answers=answers,notes=row.notes if row else '',revision=row.revision if row else 0,
        updated_at=row.updated_at if row else None,guidance=guidance(answers),
        attachments=[dict(id=f.id,uploaded_at=f.uploaded_at,uploaded_role=f.uploaded_role,assessment_revision=f.assessment_revision,label='Uploaded CEST document — not verified by ContractPros') for f in files],
        history=[dict(revision=h.revision,actor_role=h.actor_role,created_at=h.created_at,answers=json.loads(h.answers_json),notes=h.notes,version=h.question_version) for h in history])

@router.get('/by-request/{rid}')
def read(rid:int,user:User=Depends(current_user),session:Session=Depends(get_session)):
    booking,role=access(session,user,rid)
    return view(session,booking,role)

@router.put('/by-request/{rid}')
def save(rid:int,body:Answers,user:User=Depends(current_user),session:Session=Depends(get_session)):
    booking,role=access(session,user,rid)
    if set(body.answers)-{q[0] for q in QUESTIONS}:raise HTTPException(422,'Unknown question')
    row=session.get(IR35Record,booking.id)
    if (row.revision if row else 0)!=body.expected_revision:raise HTTPException(409,'Another participant updated this assessment. Reload before saving.')
    row=row or IR35Record(booking_id=booking.id)
    row.answers_json=json.dumps(body.answers);row.notes=body.notes.strip();row.revision+=1;row.updated_by=user.id;row.updated_at=datetime.utcnow();row.question_version=VERSION
    session.add(row)
    session.add(IR35History(booking_id=booking.id,revision=row.revision,actor_id=user.id,actor_role=user.role,answers_json=row.answers_json,notes=row.notes))
    session.commit()
    return view(session,booking,role)

@router.post('/by-request/{rid}/cest')
def upload(rid:int,file:UploadFile=File(...),user:User=Depends(current_user),session:Session=Depends(get_session)):
    booking,role=access(session,user,rid)
    existing=session.exec(select(IR35Attachment).where(IR35Attachment.booking_id==booking.id)).all()
    if len(existing)>=10:raise HTTPException(409,'Ten documents are already attached. Contact support to review retained documents.')
    data=file.file.read(MAX_BYTES+1)
    if file.content_type!='application/pdf' or not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:] or len(data)>MAX_BYTES:
        raise HTTPException(422,'Upload a PDF result, up to 4 MB.')
    # Always force download; never render user-supplied PDF on the application origin.
    key=f'ir35/{booking.id}/{uuid4().hex}.pdf'
    try:
        s3=r2_client();bucket=private_bucket_name()
        s3.put_object(Bucket=bucket,Key=key,Body=data,ContentType='application/pdf',ContentDisposition='attachment; filename="CEST-result.pdf"',CacheControl='private, no-store')
    except Exception:raise HTTPException(503,'Private document storage is unavailable. No attachment was recorded.')
    row=session.get(IR35Record,booking.id)
    attachment=IR35Attachment(booking_id=booking.id,key=key,uploaded_by=user.id,uploaded_role=user.role,assessment_revision=row.revision if row else 0)
    try:
        session.add(attachment);session.commit()
    except Exception:
        session.rollback();s3.delete_object(Bucket=bucket,Key=key);raise
    return view(session,booking,role)

@router.get('/by-request/{rid}/cest/{aid}')
def download(rid:int,aid:int,user:User=Depends(current_user),session:Session=Depends(get_session)):
    booking,_=access(session,user,rid)
    attachment=session.get(IR35Attachment,aid)
    if not attachment or attachment.booking_id!=booking.id:raise HTTPException(404,'Document not found')
    try:
        obj=r2_client().get_object(Bucket=private_bucket_name(),Key=attachment.key)
        data=obj['Body'].read(MAX_BYTES+1)
        obj['Body'].close()
        if len(data)>MAX_BYTES:raise ValueError('Oversized document')
    except Exception:raise HTTPException(503,'Document could not be retrieved. Please try again.')
    return Response(data,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="CEST-result.pdf"','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox"})
