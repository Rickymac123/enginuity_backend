# Pete production release procedure

1. **Release from `main`.** After validation passes, record the current known-good production commit. Land the validated change on `main` and record the full SHA of the resulting `main` commit as the expected release. The existing Render auto-deploy picks up changes to `main`; no separate manual deploy is needed.
2. **Verify production.** Once Render finishes, request the production `/health` endpoint. Accept the release only if it returns HTTP 200 with `ok: true` and `commit` exactly matching the full expected SHA. A healthy response with a missing or different commit does not verify the release.
3. **Revert if verification fails.** Restore the previous code by landing a new revert commit on `main`, without rewriting history. Let the same Render auto-deploy pick it up, then repeat the health and commit checks using the new revert commit’s full SHA, not the old known-good SHA.
