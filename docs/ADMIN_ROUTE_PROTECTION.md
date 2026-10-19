# FleetAI: owner access rollout checklist

Draft branch only. Do not merge into main until the user approves production release.

## Guarded write operations
Wallet topup/fine; driver debt creation/payment; driver assignment; contract creation; edit/delete financial operations; test wallet mutations; payment settings; mark rent paid/partial; add/delete car; investor assignment/reset; Telegram link/test; Wialon settings/odometer and manual command.

## Guarded read pages
Manual topup and car selection; driver debts, fines, contracts, Telegram admin; Wialon dashboards/settings.

## Exceptions that must keep independent auth
Driver public contract links, driver bank payment flow, T-Bank webhook, Render cron endpoints. Never expose sensitive data solely because a route is GET.

## Safety
Wialon 665 block is rejected before calling the command sender, regardless of session or confirmation text. Do not restore until verified hardware ignition-off/starter-only interlock and physical safety testing.

## Blockers before release
- Audit all remaining financial GET and POST routes for leaks and unintended writes.
- Review existing JS requests: same-origin check may reject some legacy fetch calls; run browser integration tests.
- Add CSRF tokens for admin login/logout and all browser write requests, or otherwise justify same-origin enforcement.
- Add distributed login rate limiting for multiple workers; current limiter is per-process.
- Configure persistent FLASK_SECRET_KEY and FLEETAI_ADMIN_PASSWORD_HASH on Render.
- Use staging database for write-path tests; verify driver/T-Bank/cron flows.
- Backup, rollback plan, explicit owner approval to merge.
