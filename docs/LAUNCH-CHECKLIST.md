# ContractPros release checklist

These changes are prepared locally. Do not deploy verified-only login until actual verification and reset emails arrive and their links work on www.contractpros.co.uk.

## Required before release

- Microsoft 365 administrator: configure the Microsoft Graph application, tenant/client ID and secret in Render secrets, MAIL_PROVIDER=microsoft_graph and MAIL_FROM=info@contractpros.co.uk. Confirm the mailbox is licensed and permitted for application mail. Restrict the application's mailbox scope. Admin permission/consent and a real inbox test remain outstanding; no passwords or secrets belong in GitHub.
- Test verification and password reset delivery to the owner's authorised inbox ricky@rickymc.co.uk, including junk folders. Confirm links and one-time token behaviour. The owner currently cannot sign into Microsoft admin.
- Provision a private Cloudflare R2 bucket, separate from the public image bucket; set R2_PRIVATE_BUCKET_NAME. Verify unauthenticated object access fails and authorised CV downloads succeed.
- Take a fresh database backup and rehearse restoration in staging. Run python -m scripts.prepare_launch against staging first, then production in a maintenance window. Duplicate records stop the migration and require manual reconciliation; do not delete automatically.
- Run python -m scripts.migrate_private_cvs as a dry run, then --apply after confirming private storage. Use --apply --remove-public-copy to remove verified old copies; this can be rerun. Inventory orphaned public CV objects separately, preserving private copies before removal. Remove any remaining public access and assess cache retention.
- Run PostgreSQL concurrency CI; the local SQLite test suite cannot prove row-lock behaviour.
- Configure and verify the internal notification/reminder job with its secret; recommend every five minutes. Confirm delivery, retry handling and monitoring of failed runs.
- Review privacy/terms operating details: retention periods, overseas hosting arrangements and rights request process. Published operator/contact details use the owner's RMC Engineering information.

## Deployment and acceptance

Apply additive schema migration before deploying backend and frontend together. Existing sessions will require sign-in again because sessions now bind to the current password. Test professional, company, agency and admin roles, including application, booking acceptance, calendar conflict prevention, qualification approval and private downloads. Confirm site health and error logs after deployment. If rollback is required, restore the previous application releases; retain additive columns and tables pending investigation, and do not roll back to publicly accessible CV URLs.

## Social sign-in

Google, Apple and Facebook developer accounts are not yet created. Existing disabled buttons must remain disabled until each provider is configured and tested. Follow SOCIAL-SIGNIN.md using www.contractpros.co.uk as the canonical domain. Creating provider accounts, accepting agreements and any paid Apple membership require the owner. Never add provider secrets to source control.

## Current limitations

Local tests capture mail; they do not establish real delivery. Live storage, production role accounts, backup restoration, PostgreSQL concurrency and external provider approvals require separate evidence before launch. No new production deployment was performed as part of these local repairs.
