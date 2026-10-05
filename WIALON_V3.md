# Wialon V3.1 diagnostic

This build defaults to the regional Wialon server used by this fleet:

`https://wialonreg.ru/wialon/ajax.html`

Required Render environment variable:

`WIALON_TOKEN`

Optional override:

`WIALON_BASE_URL=https://wialonreg.ru`

After deploy open `/api/wialon/units`. The endpoint never returns the token.
