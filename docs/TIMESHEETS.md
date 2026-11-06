# Timesheets release

Work invoicing is separate from Stripe membership billing. Keep WORK_INVOICING_ENABLED unset or false for this release. No production QuickBooks credentials or authorisation are required for timesheet submission, correction or approval.

Run `python -m scripts.prepare_launch` before serving the release. The migration adds work-billing tables and seeds the 20% default markup. It is additive and safe to rerun; take a production backup first. Rollback application code to the previous release if needed; retain the additive tables and recorded timesheets.

Admins record an agreed contractor rate per booking. Rates lock after submission. Clients can return submitted work with a reason, or approve the displayed hours and charge. Approved work is immutable. With issuing disabled, approval records `invoice_held` in the audit trail and creates no invoice queue item. Enabling issuing later does not automatically invoice this held work; a separate reviewed issuing process must be implemented before releasing held work. No contractor self-billing or payments are performed.

QuickBooks production invoicing is not approved for activation. Sandbox amounts and VAT passed, but invoice email delivery remains unconfirmed. Confirm live tax mappings, customer email, branding, OAuth logging redaction and recovery procedures before activation. Daily rates use proportional billable minutes; only record rates whose booking agreement explicitly covers that calculation.

Verification: PostgreSQL migration rerun, duplicate submissions, duplicate approval and approval-versus-return concurrency; role isolation, corrections, totals, default-off issuing and encrypted single-use OAuth state. Browser submission/correction/approval verified with synthetic accounts, no real invoices.
