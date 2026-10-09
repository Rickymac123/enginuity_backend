import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from auth.schemas import UserCreate, UserUpdate
from auth.models import User
from models.talent import Talent
from models.review import Review
from app.routers import company_talent, profile_preview


@pytest.mark.parametrize('role', ['admin', 'engineer', 'superuser', ''])
def test_registration_rejects_privileged_or_unknown_role(role):
    with pytest.raises(ValidationError):
        UserCreate(**registration(role))


def registration(role):
    return dict(email='person@example.com', password='test-password-123', role=role,
                first_name='Test', last_name='Person', phone='07000000000', address_line1='1 Test Street',
                address_line2='', city='Cardiff', postcode='CF10 1AA', country='UK',
                profession='Engineer', location='Cardiff')


@pytest.mark.parametrize('role', ['company', 'agency', 'professional'])
def test_normal_registration_still_works(role):
    assert UserCreate(**registration(role)).role == role


@pytest.mark.parametrize('field,value', [('role', 'admin'), ('role', 'company'),
    ('role', None), ('is_superuser', True), ('is_verified', True), ('is_active', False)])
def test_self_service_rejects_permission_changes(field, value):
    with pytest.raises(ValidationError):
        UserUpdate.model_validate({field: value})


def test_ordinary_profile_edit_still_works():
    assert UserUpdate(first_name='Updated').create_update_dict() == {'first_name': 'Updated'}


@pytest.fixture
def profile_client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        professional = User(id=1, email='pro@example.com', hashed_password='unused', role='professional')
        company = User(id=2, email='company@example.com', hashed_password='unused', role='company')
        session.add_all([professional, company])
        session.add_all([
            Talent(id=10, user_id=1, first_name='Pro', last_name='One', profession='Engineer', profession_category='Engineering', location='Cardiff'),
            Talent(id=11, agency_id=2, first_name='Agency', last_name='Candidate', profession='Engineer', profession_category='Engineering', location='Cardiff'),
        ])
        for ident, owner, status, visible in [(1,1,'verified',True), (2,1,'pending',True),
                (3,1,'verified',False), (4,2,'verified',True), (5,1,'',True)]:
            session.add(Review(id=ident, professional_id=owner, rating=5,
                reviewer_name='Reviewer', reviewer_email='private@example.com',
                comment='Excellent engineering work.', status=status, is_public=visible))
        session.commit()
        app = FastAPI()
        app.include_router(company_talent.router)
        app.include_router(profile_preview.router)
        def db():
            yield session
        app.dependency_overrides[company_talent.get_session] = db
        app.dependency_overrides[profile_preview.get_session] = db
        company_dependency = next(r for r in company_talent.router.routes if r.path.endswith('/profile')).dependant.dependencies[0].call
        app.dependency_overrides[company_dependency] = lambda: company
        app.dependency_overrides[profile_preview.require_professional] = lambda: professional
        yield TestClient(app)
    engine.dispose()


@pytest.mark.parametrize('path', ['/company/talent/10/profile', '/professional/me/preview'])
def test_profile_returns_only_public_verified_reviews_without_private_fields(profile_client, path):
    response = profile_client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body['review_count'] == 1
    assert body['average_rating'] == 5
    assert [r['id'] for r in body['reviews']] == [1]
    assert 'private@example.com' not in response.text
    assert not {'reviewer_email', 'invite_id', 'professional_id', 'company_id'} & body['reviews'][0].keys()


def test_agency_profile_does_not_receive_unrelated_reviews(profile_client):
    response = profile_client.get('/company/talent/11/profile')
    assert response.status_code == 200
    assert response.json()['reviews'] == []


def test_missing_profile_returns_404(profile_client):
    assert profile_client.get('/company/talent/999/profile').status_code == 404
