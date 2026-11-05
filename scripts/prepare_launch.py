"""Run before deployment: python -m scripts.prepare_launch. Back up the database first."""
from sqlalchemy import inspect, text
from app.db import engine


def migrate(engine):
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(7392841)"))
        from auth.models import User
        from models.client_terms import ClientPaymentTerms, ClientPaymentTermsAudit
        for model in (ClientPaymentTerms, ClientPaymentTermsAudit):
            model.__table__.create(connection, checkfirst=True)
        from models.billing import BillingAccount, LaunchOffer, LaunchRedemption, BillingEvent
        for model in (BillingAccount, LaunchOffer, LaunchRedemption, BillingEvent):
            model.__table__.create(connection, checkfirst=True)
        connection.execute(text("INSERT INTO launchoffer (code, redeemed, capacity) SELECT 'FOUNDERS100', 0, 100 WHERE NOT EXISTS (SELECT 1 FROM launchoffer WHERE code='FOUNDERS100')"))
        tables = inspect(connection).get_table_names()
        for table in ('bookingrequest','booking'):
            if table in tables:
                columns={c['name'] for c in inspect(connection).get_columns(table)}
                for name in ('client_payment_due_days','client_terms_revision'):
                    if name not in columns:connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} INTEGER'))
        if "review" in tables:
            if "booking_id" not in {c["name"] for c in inspect(connection).get_columns("review")}:
                connection.execute(text("ALTER TABLE review ADD COLUMN booking_id INTEGER REFERENCES booking(id)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_review_booking ON review (booking_id)"))
        if "company" in tables:
            columns = {c["name"] for c in inspect(connection).get_columns("company")}
            for name, kind in {"is_public":"BOOLEAN NOT NULL DEFAULT FALSE", "registration_number":"VARCHAR", "industry":"VARCHAR", "postcode":"VARCHAR", "logo_url":"VARCHAR", "updated_at":"TIMESTAMP"}.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE company ADD COLUMN {name} {kind}"))
            connection.execute(text("UPDATE company SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        if "talent" in tables and "cv_storage_key" not in {c["name"] for c in inspect(connection).get_columns("talent")}:
            connection.execute(text("ALTER TABLE talent ADD COLUMN cv_storage_key VARCHAR"))
        if "talent" in tables:
            columns = {c["name"] for c in inspect(connection).get_columns("talent")}
            for name, kind in {"representation_confirmed_at":"TIMESTAMP", "notice_provided_on":"DATE", "notice_delivery_method":"VARCHAR", "notice_version":"VARCHAR"}.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE talent ADD COLUMN {name} {kind}"))
        if "booking" in tables:
            duplicate = connection.execute(text("SELECT booking_request_id FROM booking GROUP BY booking_request_id HAVING COUNT(*) > 1 LIMIT 1")).first()
            if duplicate:
                raise RuntimeError("Duplicate booking requests require reconciliation before migration")
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_request ON booking (booking_request_id)"))
        if "talentapplication" in tables:
            duplicate = connection.execute(text("SELECT jobpost_id, talent_id FROM talentapplication GROUP BY jobpost_id, talent_id HAVING COUNT(*) > 1 LIMIT 1")).first()
            if duplicate:
                raise RuntimeError("Duplicate applications require reconciliation before migration")
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_talent_application ON talentapplication (jobpost_id, talent_id)"))

if __name__ == "__main__":
    migrate(engine)
    print("Launch schema migration complete")
