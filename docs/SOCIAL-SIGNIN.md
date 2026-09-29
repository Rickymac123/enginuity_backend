# Signup and social identity configuration

## Server environment

FRONTEND_BASE_URL=https://www.contractpros.co.uk
SECRET=<existing strong application signing secret, at least 32 characters>

Google:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET

Apple:
- APPLE_CLIENT_ID (web Services ID)
- APPLE_TEAM_ID
- APPLE_KEY_ID
- APPLE_PRIVATE_KEY (Sign in with Apple .p8 key; literal or escaped newlines)

Facebook:
- FACEBOOK_CLIENT_ID (app ID)
- FACEBOOK_CLIENT_SECRET
- FACEBOOK_API_VERSION (a supported version selected for the app, e.g. vXX.X; do not use the placeholder)

Store these values in the hosting provider's secret settings, never in GitHub or frontend public variables. Preserve the current signing secret rather than rotating it incidentally during setup. A provider is advertised only when all of its required values and the canonical HTTPS frontend origin are configured. Presence checks do not prove provider approval or credential validity.

## Provider consoles

Google: create a web OAuth client, configure consent/branding and permitted test users, and register https://www.contractpros.co.uk/api/social/google/callback. Only basic identity/email scopes are requested.

Apple: enable Sign in with Apple for the appropriate primary App ID, associate a web Services ID and website domain, register https://www.contractpros.co.uk/api/social/apple/callback, and create the corresponding private key. The implementation generates short-lived client-secret JWTs from that key. Rotate keys deliberately. The form collects names itself; Apple is only asked for email.

Facebook: configure Facebook Login for the website, select the app's supported Graph API version and register https://www.contractpros.co.uk/api/social/facebook/callback. Configure test users and complete the app's required access/review steps before release. Facebook email is verified by a ContractPros email link after first signup, because the Graph response is not an OIDC email_verified claim.

Reference documentation checked during implementation:
- https://developers.google.com/identity/openid-connect/openid-connect
- https://developer.apple.com/documentation/signinwithapplerestapi
- https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/
  (Meta's documentation fetch was rate-limited; production verification against the app's selected API version remains required.)

## Database and release order

This change requires three new tables: socialidentity, socialflow and registrationemail. socialidentity has a unique (provider, subject) constraint. socialflow contains hashed one-use state/tickets, a hashed browser binding, short-lived nonce/PKCE values and pending signup email, expiring after ten minutes. No provider access/refresh tokens or provider passwords are persisted. Expired flow rows are removed on subsequent starts; schedule cleanup below for quiet deployments.

registrationemail is a transient unique-key lock used during account creation; it is deleted in the same transaction before commit. Existing users are checked by case-insensitive email both before and after acquiring this lock. This protects new signup races without reserving deleted users' addresses forever. Test against the production PostgreSQL version/isolation settings before launch; local concurrency coverage uses SQLite.

The existing startup init_db imports these models and creates missing tables. For a controlled release, back up and test in staging, then use `python scripts/prepare_social_auth.py` against the intended database before starting the new backend. The script creates only these tables and deletes expired temporary flows. It does not alter existing user or talent columns or delete accounts. No production migration has been run by this task.

Deploy backend first, then the matching frontend. Email signup remains usable while social providers are unconfigured. Rollback can restore previous application versions while retaining these additive tables. A frontend rollback should not be treated as revoking already issued sessions.

## Account behavior and verification

Public role choices remain company, agency and professional. Privilege flags are rejected. Signup requires a password of 12–128 characters and nonblank contact/address/name fields. Professional accounts and their initial Talent profile are written atomically; older clients without profession_category default to 'other'.

Provider subject IDs identify accounts. Existing accounts are never linked solely by matching email. An email collision requests the original sign-in method. New social users complete their role and contact/profile details before any application session is issued. Google and Apple require signed, issuer/audience/expiry/nonce-validated ID tokens with verified email. Google uses PKCE. Facebook access tokens are inspected for this app and checked against the returned user ID, followed by local email verification. Disabled accounts cannot use social login.

## Tests and remaining verification

Run `python -m pytest -q tests`. The tests use isolated databases and intercepted provider responses, including cryptographically signed test identity tokens. They check account creation, rollback, duplicate/concurrent signup, deleted-email reuse, all three social journeys, invalid/replayed/expired browser state, email collisions, inactive accounts and invalid identity claims.

The browser fixture (`CONTRACTPROS_LOCAL_TESTS=1 python -m uvicorn tests.browser_server:app --host 127.0.0.1 --port 8001`) always uses a new temporary SQLite database and captures test email rather than sending it. Do not deploy this fixture.

Still required: real provider consent tests, canonical-domain HTTPS/cookie checks, production SMTP delivery, PostgreSQL migration/concurrency checks and deployment-level abuse/rate limits. This task does not resolve all pre-existing API authentication, CSRF/CORS or account-recovery issues elsewhere in the application.
