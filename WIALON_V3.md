# Wialon V3 diagnostic

After deploying and setting `WIALON_TOKEN` in Render, open:

`/api/wialon/units`

The endpoint logs in with the server-side token and returns visible Wialon units and highlights the first unit whose name contains `665`. The token is never returned to the browser.

Optional environment variable: `WIALON_API_URL` (defaults to `https://hst-api.wialon.com/wialon/ajax.html`).
