import sys
import pytest
from sqlmodel import SQLModel, Session, create_engine, select, update
from sqlalchemy.pool import StaticPool
from models.talent import Talent
from scripts import migrate_private_cvs as migration

@pytest.mark.parametrize('scenario', ['normal', 'mismatch', 'newer-upload'])
def test_private_copy_verification_and_newer_upload_preservation(monkeypatch, scenario):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Talent(id=1, user_id=1, first_name='Test', last_name='Professional', profession_category='engineering', profession='Engineer', location='London', cv_url='https://public.example/cvs/user_1.pdf'))
        session.commit()
    copied = []; deleted = []
    class Storage:
        def head_object(self, Bucket, Key):
            return {'ContentLength': 10, 'ETag': 'different' if scenario == 'mismatch' and Bucket == 'private' else 'same', 'ContentType': 'application/pdf'}
        def copy_object(self, **kwargs):
            copied.append(kwargs)
            if scenario == 'newer-upload':
                with Session(engine) as uploader:
                    uploader.exec(update(Talent).where(Talent.id == 1).values(cv_storage_key='cvs/newer.pdf', cv_url='/api/uploads/cv/1'))
                    uploader.commit()
        def delete_object(self, **kwargs): deleted.append(kwargs)
    monkeypatch.setattr(migration, 'engine', engine)
    monkeypatch.setattr(migration, 'r2_client', lambda: Storage())
    monkeypatch.setattr(migration, 'bucket_name', lambda: 'public')
    monkeypatch.setattr(migration, 'private_bucket_name', lambda: 'private')
    monkeypatch.setattr(migration, 'public_base_url', lambda: 'https://public.example')
    monkeypatch.setattr(sys, 'argv', ['migration', '--apply'])
    if scenario == 'mismatch':
        with pytest.raises(RuntimeError, match='Copy verification failed'): migration.main()
    else:
        migration.main()
        migration.main()
    with Session(engine) as session:
        talent = session.get(Talent, 1)
        expected = {'normal': 'legacy/cvs/user_1.pdf', 'mismatch': None, 'newer-upload': 'cvs/newer.pdf'}[scenario]
        assert talent.cv_storage_key == expected
        assert talent.cv_url == ('https://public.example/cvs/user_1.pdf' if scenario == 'mismatch' else '/api/uploads/cv/1')
    assert len(copied) == 1
    assert deleted == []
    engine.dispose()
