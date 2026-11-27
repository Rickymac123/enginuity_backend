# Registration reporting

New successful account creations write an anonymous event in the same transaction as the account, for password and social registration. Events contain a random ID, UTC creation time and role. Existing registration dates are not reconstructed.

`GET /admin/marketing-signups?period=7d` uses the existing verified administrator dependency. `GET /internal/marketing/signups?period=7d` accepts a dedicated Bearer token from `MIA_SIGNUP_METRICS_TOKEN`; it is disabled unless a token of at least 32 characters is configured. Supported periods are today, 7d and 30d, using Europe/London calendar boundaries. The token grants access to this fixed aggregate report only.

The response separates current account inventory, recorded account creations, incomplete history and complete-period counts. It includes owner, administrator and test accounts; it does not claim paying customers or campaign attribution. Counts refresh when queried. No personal identifiers are returned or retained in event rows.

The machine connection is prepared but must be explicitly commissioned before calling it connected. Keep its token in the hosting environment and encrypted Command Centre settings, never in the repository, logs, browser URL or a public script.
