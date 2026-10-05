# V5 — debt/blocking preview for 665

- Adds read-only `/api/driver-mvp/665/blocking-preview`.
- Driver portal shows active/debt status.
- `/wialon-665` shows whether current debt would trigger blocking.
- Automatic Wialon blocking remains OFF. Manual V4 buttons remain available.
- Optional Render env `DRIVER_BLOCK_DEBT_THRESHOLD` controls preview threshold (default 1 ruble).
