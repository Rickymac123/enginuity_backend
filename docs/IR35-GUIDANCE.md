# Booking IR35 guidance

This is an evidence and guidance workflow, not a tax-status determination engine. There are no weights, percentages, inside/outside conclusions, formal SDS generation, HMRC endorsement or professional validation claims. Original prompts are based on public HMRC guidance, not copied Kingsbridge questions or proprietary scoring.

Sources reviewed 8 November 2026:
- https://www.gov.uk/guidance/check-employment-status-for-tax
- https://www.gov.uk/government/publications/help-to-comply-with-the-reformed-off-payroll-working-rules-ir35-gfc4/making-status-determinations-part-8

Each confirmed booking has its own assessment. Its client, directly booked professional or representing agency, and administrators can read and revise it. All saved revisions are retained with actor ID/role and time. Unknown/missing answers, personal-service/substitution conflicts, office-holding and intermediary-scope concerns require further review. Completing questions never confirms tax status. Final responsibility, applicability (including client size/supply chain) and any formal SDS process must be established separately.

CEST PDF uploads are supporting evidence only, not authenticated HMRC results. Uploads are limited to 4 MiB and ten per booking; metadata records uploader and the assessment revision at upload. A later revision warns the user to check currency. Documents use the existing private R2 bucket, random server-generated keys and authenticated download through the application; keys are never returned. Downloads force attachment with no-store/nosniff. Basic PDF envelope checks are not antivirus scanning. Support must review/remediate incorrect uploads and legal holds under the documented retention process; no public sharing or automatic deletion is added. Treat IR35 records and CEST documents as confidential booking evidence within the existing six-year minimum booking-evidence retention schedule, subject to documented review/holds.

Deployment adds three new tables through the existing model-registration/startup create_all mechanism; no existing columns or records are rewritten. Backend precedes frontend. Existing private storage configuration is required; failure is shown without recording a successful attachment. No new storage account, keys, mail delivery or tax/payment/invoice setting is enabled.

Tests cover participant access, unrelated-account denial, revision conflicts/history, invalid/oversized uploads, cross-booking download denial and storage failure. Test storage is isolated. Production private-bucket write/read and authenticated live journey still require release verification. Roll back the frontend links/page and router if needed; preserve the new tables and private objects.
