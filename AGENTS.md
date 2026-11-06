# FleetAI agent instructions

## Scope and safety
- This repository powers a live taxi-fleet rental and finance application. Production: https://fleetai-1.onrender.com.
- Never deploy, modify Render, access or mutate the production database, rotate secrets, or merge into main without explicit owner approval.
- Work on the assigned feature branch only. Never force-push.
- Do not log, print, commit, or paste credentials, .env files, customer identity documents, driver data, or database dumps.
- Before a change, inspect only the relevant modules and tests; use targeted search rather than dumping the whole repository.
- Prefer small commits, minimal diffs, and concise final reports: files changed, tests run, failures, risks, commit SHA.

## Architecture and financial invariants
- Python/Flask application, SQLAlchemy persistence, PostgreSQL in production.
- Finance records in FleetAI are authoritative; Hermes is not a second ledger.
- Driver debt and rental arrears may be separate concepts: do not add them together without checking semantics.
- Financial GET handlers may have legacy write side effects (rent accrual, settlement creation, downtime sync). Do not casually rewrite them as pure reads without replacement jobs and regression tests.
- Never break verified T-Bank webhook signatures, confirmed-payment checks, idempotency, or Telegram webhook verification.
- Owner access requires a server-side authenticated session and CSRF protection for browser mutations.
- Driver access must be scoped to the authenticated driver and their current assignment; car code alone is not authorization.
- Hermes credentials must be separately revocable and restricted to new read-only finance routes (finance:read). Never reuse owner credentials or CRON_SECRET.
- Protect all finance reads and writes with server-side authorization. Preserve existing workflows through tests.

## Token-efficient workflow
1. Read this file and inspect git status/diff before changing anything.
2. Find the specific handler and adjacent tests; avoid loading all routes.py or full log histories unless necessary.
3. Make the smallest safe change. Do not run broad audits repeatedly.
4. Run syntax checks and focused tests first; run full suite only when needed or before handoff.
5. Let GitHub Actions perform routine checks; read its short failure summary instead of rerunning identical commands.
6. Never use a model to reformat huge test logs. Summarize the failing test name and relevant traceback only.

## Local verification
- Install dependencies from requirements.txt in an isolated virtual environment.
- Run `python -m compileall -q app.py fleetai` for a quick syntax check.
- Run focused tests for touched code using the test runner actually present in the working tree.
- Use only an isolated test database; never run tests against a production DATABASE_URL.

## Stage-one goal
Secure owner and driver authentication, implement independent read-only Hermes finance endpoints, and test negative authorization cases and legacy payment/contract behavior. Do not deploy.
