# FleetAI finance change review (human and agent)

Use this checklist for a focused review of financial-authentication changes. It is not a replacement for running tests.

## Review boundaries
1. Identify changed routes, decorators, session code, and migrations from `git diff --stat`.
2. Check that anonymous finance reads and writes are denied; confirm legitimate owner sessions still work.
3. Verify driver sessions cannot access a different car, another driver, or a previous assignment.
4. Confirm Hermes `finance:read` can only call new read-only routes; cannot call legacy GET endpoints with side effects or POST/PUT/PATCH/DELETE.
5. Confirm one-time Telegram login links expire, cannot be reused, and bind to a verified Telegram chat.
6. Confirm browser mutations have CSRF protection and cookies use secure settings in production.
7. Compare T-Bank signature verification, confirmed-payment checks, idempotency, and contract-signing flows with the base revision.
8. Confirm test fixtures use isolated storage and do not reference production secrets or endpoints.
9. Report only: pass/fail per boundary, focused test command/results, and unresolved risks.

## Commands
- `git diff --stat <base>...HEAD`
- `python -m compileall -q app.py fleetai`
- Run only the relevant test files for the changed modules; full suite at milestone handoff.

## Do not
- Treat an HTTP 200 as proof that authorization works.
- Assume a car number or contract token proves driver identity.
- Disable bank/Telegram webhook checks or replace them with browser session requirements.
- Trigger cron, bank test payment, or production financial-write endpoints during verification.
- Deploy or merge without owner approval.
