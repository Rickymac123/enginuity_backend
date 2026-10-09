"""Create an account and its initial professional profile in one transaction."""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from fastapi_users import exceptions
from auth.models import User
from models.talent import Talent
from models.social_auth import RegistrationEmail


def create_account(session, payload, password_hash, verified=False):
    email = str(payload.email).strip().lower()
    if session.exec(select(User).where(func.lower(User.email) == email)).first():
        raise exceptions.UserAlreadyExists()
    try:
        claim = RegistrationEmail(email=email)
        session.add(claim)
        session.flush()
        # Recheck after obtaining the unique-key lock: another signup may
        # have committed while this transaction was waiting.
        if session.exec(select(User).where(func.lower(User.email) == email)).first():
            raise exceptions.UserAlreadyExists()
    except IntegrityError:
        session.rollback()
        raise exceptions.UserAlreadyExists()
    values = payload.model_dump(exclude={'password', 'is_active', 'is_superuser', 'is_verified'})
    user = User(**{key: value for key, value in values.items() if key in User.model_fields})
    user.email = email
    user.hashed_password = password_hash
    user.is_active = True
    user.is_verified = verified
    user.is_superuser = False
    session.add(user)
    session.flush()
    if payload.role == 'professional':
        session.add(Talent(user_id=user.id, agency_id=None,
            first_name=payload.first_name, last_name=payload.last_name,
            profession_category=payload.profession_category or 'other',
            profession=payload.profession, location=payload.location,
            postcode=payload.postcode))
        session.flush()
    # Keep the database lock until commit, without permanently reserving
    # deleted accounts' email addresses.
    session.delete(claim)
    session.flush()
    return user
