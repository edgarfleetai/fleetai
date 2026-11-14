# Legacy boundary regression tests

Run from the repository root:

```sh
.venv-security/bin/python -B -m pytest -p no:cacheprovider --basetemp=.test-data/legacyworker tests/test_legacy_boundaries.py -q
```

## Coverage

- The real `tbank.verify_notification` validates independently calculated SHA-256 signatures, including JSON booleans, excluded nested objects and null fields. Missing, invalid and tampered signatures cannot post financial rows.
- A signed confirmed payment for a synthetic vehicle creates exactly one original Operation, Income and DriverWalletTransaction, marks the pending DriverBankPayment paid, and acknowledges replays without duplicates. Both original SBP 2% and card 4% wallet fees are asserted; financial income remains the full gross payment.
- Signed unsuccessful/unconfirmed notifications acknowledge `OK` without posting or marking the pending payment paid.
- Telegram fails closed with no configured secret, a missing header or a mismatched header before sending or issuing credentials. A valid authenticated ignored command works without an owner session. Unbound private, nonprivate and sender/chat mismatch `/login` requests create no DriverTicket. Only Telegram delivery and the credential-URL issuance boundary are mocked; endpoint authorization and database queries remain real.
- Invalid capability tokens reach the original 404 responses for contract GET/save/send-code/sign/preview/PDF, without an owner session. The actual contract table initializer works on isolated SQLite, including its BYTEA column; no SQL adaptation or authorization mocking was required.
- Six original service method/path combinations fail closed without an exact CRON_SECRET and run real handlers with an empty synthetic fleet when authenticated by query string. The two dual-method cron routes preserve GET/POST and header authentication. No owner session is created.

## Isolation and limits

Uses the shared secure_app fixture and conftest transport/database guards. All identifiers and credentials are synthetic; all database access is local isolated SQLite. No real bank/TG calls, production database, actual external jobs, commits or pushes.

Bound Telegram login is covered by the parent integration suite, not duplicated here. Owner-authenticated archive and daily-rent behavioral scenarios are outside this file; empty-fleet cron checks do not establish populated-fleet rent calculations. Watcher/setup service handlers that can trigger actual jobs are deliberately not invoked with valid credentials. PostgreSQL behavior, live bank acquisition and live Telegram/SMS delivery are not exercised.

Verified result: **51 passed, 13 warnings**. Warnings are existing ReportLab ast.NameConstant and Python 3.12 SQLite datetime-adapter deprecations. Initial execution exposed a test-only model-name mismatch (DriverLoginToken instead of DriverTicket); only the new test file was corrected, with no application-code changes.
