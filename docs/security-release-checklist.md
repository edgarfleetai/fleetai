# FleetAI security release checklist (feature branch)

This branch is **not** approved for production deployment.

## Verified by isolated CI
- Owner-only route policy and private API access.
- Wialon 665 engine block command is denied (no hardware safety verification).
- Same-origin admin writes and reverse-proxy HTTPS handling.
- Admin response security headers.
- Admin login cross-origin rejection (subject to latest CI run).

## Outstanding before production
- Audit all browser fetch/XHR calls for Origin/Referer behavior, including browsers that suppress Referer.
- Replace Origin/Referer-only write protection with session-bound CSRF tokens, including login and logout. Coordinate frontend changes and test public webhook exemptions.
- Implement a shared login rate limiter for multi-worker/multi-instance production (Redis or WAF). The existing in-memory limiter is process-local.
- Add PostgreSQL-backed integration tests for wallet, debt, investor and warehouse operations; isolated security tests do not validate database transactions.
- Confirm Render proxy topology and forwarding headers before enabling FLEETAI_TRUST_PROXY=1. Do not trust arbitrary client-supplied forwarded headers.
- Configure persistent FLASK_SECRET_KEY and FLEETAI_ADMIN_PASSWORD_HASH as server secrets, then validate authentication in a non-production environment.
- Review the full Flask URL map for any newly added sensitive endpoints missing from the explicit owner-only policy.
- Review bank webhook signature/authentication separately; do not apply browser CSRF rules to trusted machine-to-machine callbacks.
- Require separate approval before merging to main or deploying to Render.
- Never enable remote engine blocking until an independent hardware safety assessment confirms engine-off and starter-only interlock.

## Rollout gate
1. All required CI and PostgreSQL integration tests green.
2. Browser smoke tests of login, logout, finance, warehouse and Wialon read-only views.
3. Documented rollback plan and validated backup.
4. Explicit owner approval for main merge and production deployment.
