# ContractPros billing release — 3 November 2026

## Approved catalogue
Companies GBP29 monthly / GBP290 annually excluding 20% VAT (totals GBP34.80 / GBP348). Agencies GBP59 / GBP590 excluding VAT (GBP70.80 / GBP708). Professionals remain free. Annual payment is upfront and recurring. Cancellation stops renewal at the end of the paid period.

FOUNDERS100 grants three calendar months from redemption, first 100 company/agency businesses combined, one redemption per business. No card, Stripe subscription or automatic conversion. A business profile is required. Registration number/name deduplication is not independent identity verification; support must review suspicious duplicate businesses. Existing booking management and history remain available when access expires.

## Rollout
Billing defaults OFF. Run scripts/prepare_launch.py before deploying routes. This creates four additive tables and seeds the offer without resetting its counter. Take a fresh database backup first. Deploy backend before frontend. Keep BILLING_ENABLED=false until provider acceptance tests complete. Disabling this flag restores unrestricted business activity but does NOT cancel existing Stripe subscriptions or stop charges: manage those explicitly in Stripe.

Server-only configuration: BILLING_ENABLED, STRIPE_MODE (test/live), STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_COMPANY_MONTH, STRIPE_PRICE_COMPANY_YEAR, STRIPE_PRICE_AGENCY_MONTH, STRIPE_PRICE_AGENCY_YEAR, STRIPE_UK_VAT_RATE, STRIPE_PORTAL_COMPANY, STRIPE_PORTAL_AGENCY. Never put secrets in NEXT_PUBLIC variables or repository files. Keep test and live databases, customers, keys and IDs separate.

Live checkout additionally requires STRIPE_UK_RESTRICTIONS_VERIFIED=true. Set it only after confirming and testing UK billing-country restrictions in Stripe. The application declaration alone does not enforce the payer's billing country. Do not add account-wide restrictions that would inadvertently affect other RMC services. Check any extra Stripe feature charges with the owner before enabling them.

Use GBP recurring fixed prices with exclusive tax behavior and a GB 20% exclusive VAT rate. Seller is RMC Engineering & Automation Ltd, company15908190, VAT GB506942485 (confirmed from connected QuickBooks). Configure seller invoice details in Stripe before live billing. Subscription charges are platform membership only, not contractor work payments.

Portal: invoice history, payment-method updates, cancellation at period end. Disable quantity changes, cross-role plan changes, promotions and trials. Current test configuration disables plan switching; users may cancel then choose another interval after expiry. Do not enable a public portal login link. Application sessions bind the authenticated user to a server-owned customer.

Webhook: POST https://enginuity-backend-kdve.onrender.com/billing/webhook. Subscribe to customer.subscription.created/updated/deleted, checkout.session.completed/expired, invoice.paid/payment_failed/payment_action_required. Use endpoint signing secret and matching mode. Endpoint verifies signatures, timestamp and mode; retrieves latest subscription state; deduplicates event IDs. Events for unrelated customers are ignored. Monitor failures and retry delivery. A success-page return never grants membership.

Enable the existing scheduled notification worker for founder welcome and expiry reminders. Confirm branded messages reach a controlled real inbox. Stripe invoice/receipt/payment-failure emails need account settings and delivery checks separately.

## Test-mode objects created
Stripe account acct_1S8JVyDWhODaeXAS, livemode=false.
Company product contractpros_company: monthly price_1UXr3WDWhODaeXASBHpZBHkq; annual price_1UXr3sDWhODaeXASw6fc6qdR.
Agency product contractpros_agency: monthly price_1UXr3fDWhODaeXAScS7YKRd5; annual price_1UXr3vDWhODaeXAS6HRide4q.
VAT txr_1UXr4CDWhODaeXASiMpol8C7.
Portal bpc_1UXr4NDWhODaeXASV7Rt3tZq for both roles (no plan switching).
No live catalogue or customer charges created.

## Acceptance evidence and remaining checks
Local tests cover access expiry, professional free access, quota/deduplication, checkout idempotency including timeout recovery, server-owned prices/customer, signature validation, stale/duplicate events, failure and cancellation states, reminders. Browser redemption succeeded in isolated preview and expires 3 February 2027 from 3 November 2026. Frontend build passed before final origin-guard correction; rerun before release. PostgreSQL concurrency tests require isolated PostgreSQL and remain a release gate.

Still required: full Stripe-hosted checkout for both roles and intervals, UK/foreign address handling, authentication/declined cards, webhook retry/reordering, renewal and failed renewal using test clocks, cancellation and expiry, billing portal invoice/card update, receipt delivery, and a reviewed production activation. Mocked tests are not proof of provider integration. Record outcomes before enabling live billing.

Official references: https://docs.stripe.com/api/checkout/sessions/create ; https://docs.stripe.com/api/customer_portal/sessions/create ; https://docs.stripe.com/events/manage-webhook-endpoints ; https://docs.stripe.com/radar/rules/reference
