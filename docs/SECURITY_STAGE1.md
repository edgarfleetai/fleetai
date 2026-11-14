# FleetAI security: stage 1 (local branch, no deployment)

Branch: `security/hermes-finance-readonly-20261106`.

## Scope and invariants

- This stage must not deploy, modify Render, connect to a production database, or push to main.
- Existing rent synchronization, downtime reconciliation and period archiving inside legacy GET handlers remain in place. Authentication and CSRF protect the existing UI; Hermes never receives access to those handlers.
- Production commit and actual Render jobs are not confirmed. Matching the deployment and validating jobs remain a release gate, not a prerequisite for isolated code tests.
- No owner is automatically created and no default password exists. Initial owner registration is a local interactive administrative command; do not expose a public first-owner registration endpoint.
- Hermes credentials are separately revocable and only usable for the dedicated `/api/integrations/hermes/v1/` API. A read-only HTTP method is not authorization to call a legacy route.
- Driver login tickets are single-use, short-lived and delivered only to a currently bound private Telegram chat. A fresh `/login` or `/cabinet` command issues another ticket. URL fragments keep the raw ticket out of ordinary HTTP access logs.
- An explicit assignment is a new access epoch even when the driver name is unchanged. It invalidates sessions, tickets and previous Telegram binding/issuance links. Rebinding is required. Actual driver changes through legacy ORM flows must also invalidate access.

## Browser compatibility

Owner and driver sessions use Secure/HttpOnly/SameSite cookies. Authenticated legacy HTML receives a synchronous same-origin client script before its own scripts. This wrapper retrieves the session's CSRF token and attaches it to existing same-origin API fetch calls. Legacy API GETs require CSRF by default, with a small inspected SELECT/document navigation allowlist; new routes do not silently inherit an exemption. Vehicle-license GET is now SELECT-only because its table is initialized at startup, so an authorized owner/assigned driver can download PDF by an ordinary link. No rent business logic is moved out of legacy GETs in this stage.

Login and driver-ticket consumption require an exact Origin or same-origin Fetch Metadata proof. HTTPS behind a reverse proxy uses an explicit PUBLIC_BASE_URL / FLEETAI_PUBLIC_BASE_URL, not arbitrary forwarded headers. Driver login URL generation requires that explicit staging HTTPS origin; there is no fallback to the production domain.

Driver sessions may access only the assigned vehicle's cabinet, limited state/license reads and payment creation; they do not receive owner operations or Hermes access. Existing contract capability routes retain their independent token/call-confirmation checks. Existing Telegram and bank webhooks remain separate from owner/browser authentication.

Telegram webhook authentication must be configured and mandatory. Releasing this branch without matching the Telegram sender and receiver configuration will fail closed and stop processing; therefore configuration confirmation is a mandatory deployment gate. Existing cron query-secret support is retained for compatible callers until real job configuration is audited.

Bank simulator and test-credit routes are not public production functions. The real bank webhook retains signature verification, confirmed-status handling and duplicate protection. Incoming bank payloads are no longer logged verbatim.

## Isolated tests

Use only the repository-specific virtualenv and test tree:

```sh
.venv-security/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts --no-audit --no-fund
PYTHONDONTWRITEBYTECODE=1 .venv-security/bin/python -B -m pytest -p no:cacheprovider --basetemp=.test-data/acceptance tests
```

`tests/conftest.py` sets an explicit SQLite database before importing FleetAI, removes service credentials from the test process, rejects non-SQLite SQLAlchemy connections and SQLite paths outside `.test-data`, and blocks real socket and requests transports. The test client supplies browser Fetch Metadata by default; dedicated negative cases remove Origin/Fetch Metadata and prove denial. Test doubles may replace transport functions with synthetic responses; they must not perform external calls. The factory independently refuses test database paths outside `.test-data` and disables legacy fleet seeding in test mode.

The complete PostgreSQL schema and revocation triggers also execute in a disposable in-process PostgreSQL-WASM (PGlite) engine, with READ ONLY denial, rollback and assignment ABA/delete checks. This is not a native psycopg/network-pool acceptance test. Required development-only Node dependency is lockfile-pinned; no service credentials are passed to the Node harness.

## Ordered schema and minimum finance datasource

Schema initialization is explicit: register metadata, create missing tables, run idempotent inspected legacy migrations, then install revocation triggers. PostgreSQL uses one transaction and an advisory lock across this sequence. Mandatory errors stop startup rather than being swallowed. This fixes upgrading a legacy cars table that does not yet contain driver.

Outside TESTING, the new finance API requires a distinct FINANCE_READONLY_DATABASE_URL provisioned with SELECT-only rights on the required finance tables/columns. Missing datasource returns 503; it never falls back to the application's writer connection. A READ ONLY transaction adds a second boundary. Provisioning the role/password/DSN belongs to a separately approved isolated staging environment; nothing has been created on Render or production.

No real password, bearer credential, login ticket, bank signature or webhook secret should be included in the user-facing test report.

## Release gates still required

1. Independent review of the final diff and green isolated regression suite.
2. Confirm the deployed SHA, actual scheduled jobs, caller methods and service secrets' presence (never values).
3. Owner bootstrap procedure, credential custody and revocation/runbook agreed; no secrets entered in chat.
4. Staging checks of browser owner flow, driver binding/reassignment/login, contract signing, signed bank notifications and repeated notifications, Telegram binding, cron authentication and rent processing.
5. Separate explicit approval for any production schema migration, configuration update, merge, deployment or real transport test.
