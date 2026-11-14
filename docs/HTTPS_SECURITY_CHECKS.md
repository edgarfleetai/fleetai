# Local HTTPS / reverse-proxy security acceptance

This **opt-in CLI**, outside `tests/`, exercises the real production-mode Flask factory over real sockets. It does not use `Flask.test_client`, does not load `tests/conftest.py`, and must run in a **fresh Python process**. Do not import it into a live application or run it against production.

## Run after application source is frozen

From the repository root:

```sh
.venv-security/bin/python -B security_checks/https/run.py \
  --artifacts-dir /Users/daria/.hermes/profiles/fleetai/cache/scratch/https-security-final
```

Portable form: replace `.venv-security/bin/python` with the isolated environment's Python and supply an absolute artifacts directory **outside this repository**. No credentials, existing database, host URL or service tokens are accepted. Assertions must be enabled (`-O` / `PYTHONOPTIMIZE` is rejected).

The runner prints named PASS/RED results and the path to a per-run `report.json`. Exit zero requires every selected case, no unexpected blocked boundary attempt, stopped server threads, and unchanged application source hashes. Any source change during execution invalidates the receipt; rerun only after the coordinating parent authorizes/finalizes the source freeze. A test RED is evidence to report, not permission to change application security.

Dependencies: Python **3.10+**, the application's `requirements.txt` (including Flask/Werkzeug, requests, SQLAlchemy, ReportLab), and an `openssl` executable on PATH (OpenSSL or macOS LibreSSL). No pytest, browser, paid service, cryptography package, Docker or PostgreSQL installation is required. On the worker's existing environment `cryptography` was absent; certificate generation uses OpenSSL instead and no package installation was performed.

## Isolation and transport

- Starts two AF_INET TCP listeners only: HTTPS front proxy and Werkzeug HTTP backend, each bound to `127.0.0.1:0`. Their exact resolved `(127.0.0.1, allocated_port)` pairs are the only permitted TCP destinations. Other loopback ports, IPv6 destinations, external IPs, DNS, datagram sends and subprocess creation during application execution are denied.
- A one-day synthetic CA signs a separate `localhost` leaf with DNS SAN. Both private keys are created under a mode-0700 per-run directory outside Git and deleted immediately after loading the server SSL context. The CA/leaf public certificates and both SQLite fixtures are removed on exit; the redacted JSON receipt remains. Cleanup runs on ordinary failures and exceptions, not only success. Uncatchable process termination cannot guarantee cleanup.
- OpenSSL certificate subprocesses finish **before application imports and before installing the subprocess denial hook**. Their environment is minimal and does not inherit service credentials. Afterward, no application subprocesses are allowed. The guard is a process-local Python audit control, not an OS sandbox against malicious native extensions.
- `localhost` resolves deterministically to `127.0.0.1`. urllib3's irrelevant import-time IPv6 bind capability probe is disabled only while importing the harness HTTP transport. Application authentication/policy is not replaced.
- The client trusts only this run's synthetic CA, verifies hostnames, ignores proxy environment variables, and only sends application requests to the exact canonical HTTPS origin. Guard selfchecks attempt plaintext credential/unverified/external requests but reject them **before any transport**. Real credential-bearing client requests are HTTPS only. A no-secret plaintext probe to the TLS port cannot retrieve a login form. Secure cookies are checked not to appear in a prepared plaintext request.
- TLS terminates at the front proxy; the private synthetic loopback backend hop is deliberately HTTP, as on a TLS-terminating reverse proxy. This does **not** assert encryption of that internal hop. The proxy preserves original Host and forwards adversarial `Forwarded` / `X-Forwarded-*` hints without interpreting them as authority. A read-only WSGI observer records only backend scheme, Host and path (never query, headers or body).
- Before application imports, inherited configuration/credentials are cleared. `DATABASE_URL` points only at the new synthetic writer SQLite; `FINANCE_READONLY_DATABASE_URL` points at a separate synthetic reader file. Both SQLAlchemy and direct SQLite connects are restricted to these exact files. `TESTING=False`, `DEBUG=False`, and normal schema/migration initialization remain enabled. Only built-in `seed_cars` is stubbed to prevent real-world sample cars. No principal injection, security bypass, route replacement or notification mock is used.
- Requests originating in application/server threads are denied. External raw socket/urllib transports are also denied by the destination allowlist. A caught/suppressed blocked attempt still produces an overall RED, so swallowing an integration failure cannot hide it.

## Named acceptance scenarios

| Case | Assertions |
|---|---|
| `transport_guard_selfcheck` | Exact two listener pairs; external/other-loopback/IPv6/connect_ex/DNS denial; no private-key residue; outgoing request guard rejects plaintext credential, external and unverified requests before sending. |
| `verified_tls_real_http_backend_and_headers` | CA-verified HTTPS reaches actual HTTP backend; preserved Host; default CA trust and wrong TLS hostname both fail; plaintext front-port probe cannot serve login; Secure cookies withheld on plaintext; login/driver/session responses have no-store, nosniff, no-referrer, SAMEORIGIN and canonical-origin HSTS (`max-age=31536000`). |
| `prelogin_origin_proof_and_forwarding_spoof_denied` | Valid synthetic credentials cannot log in without same-origin proof, with hostile Origin, cross-site Fetch Metadata, or forwarding hints alone. No session issued. |
| `owner_cookie_https_session_csrf_and_logout` | Successful HTTPS owner login and session round-trip; `__Host-` cookie is Secure, HttpOnly, SameSite=Lax, host-only and Path=/; missing/wrong CSRF and hostile/HTTP Origin fail despite forwarding spoof; correct canonical Origin + CSRF logs out and revokes session. |
| `explicit_public_base_url_authoritative_behind_proxy` | Attacker Host + matching attacker Origin fails; configured canonical HTTPS Origin succeeds even though actual backend scheme is HTTP and original hostile Host/forwarding hints are preserved. Redirect remains relative `/`. This deliberately tests **configured Origin authority**, not a separate Host allowlist. |
| `driver_fragment_single_use_scope_and_revocation` | Canonical driver URL ignores hostile request context and uses fragment, not query; landing GET does not consume; query tickets rejected; missing/hostile pre-login proof fails; explicit POST consumes once; replay fails; real own-car page and financial API work; other-car/owner APIs fail; local administrative revoke kills existing session and outstanding ticket. |
| `hermes_four_reads_dedicated_datasource_denials_no_mutations` | Bearer reads debts, balances, rent-accruals and payments via HTTPS; reader-only marker proves dedicated datasource selection; POST denied; unauthenticated and owner-cookie-only reads denied; invalid bearer never falls back to owner cookie; valid bearer plus owner cookie cannot enter legacy/auth/owner routes. Full logical dumps of **both** databases are unchanged across all Hermes requests/denials. |
| `zero_unexpected_boundary_attempts` | No external integration/network/process attempt outside explicit guard selfchecks, including attempts swallowed by application handlers. |

Fixture values are synthetic (`HTTPSA`, `HTTPSB`, random owner password, random bearer/tickets). A synthetic Telegram binding is inserted locally only to satisfy the **real** verified-binding requirement; nothing is sent to Telegram. Driver revocation is a local administrative helper call against that fixture, not a remote owner action. The isolated reader is a separate SQLite file; this is not a substitute for provisioning/testing PostgreSQL SELECT-only privileges in deployment.

## Preliminary development smoke (not acceptance)

```sh
.venv-security/bin/python -B security_checks/https/run.py --smoke \
  --artifacts-dir /Users/daria/.hermes/profiles/fleetai/cache/scratch/https-worker-preliminary
```

This selects only guard selfchecks and transport/public endpoint checks, plus the zero-unexpected-attempts gate. It creates synthetic fixture rows but sends no real login, logout, ticket-consumption, financial or notification request; only public GETs and rejected transport probes. Its receipt is labeled `PRELIMINARY_SMOKE`, never full security acceptance.

Development smoke was exercised successfully against the worker-time source, after correcting harness-only IPv6 probe and LibreSSL certificate-subject issues. The full acceptance scenarios were intentionally **not executed by this worker** because the parent was modifying application source concurrently; the final command above must run against frozen source. Exact evidence paths belong in the parent report, not as a portable acceptance guarantee here.

## Gaps / interpretation

- Protocol checks use requests and real TLS/HTTP, not a JavaScript/browser engine. Fragment omission is exercised on the network, and landing-page fragment-clearing/explicit-confirmation code is checked, but JS execution, browser-specific `__Host-` enforcement and UI behavior need separate browser acceptance.
- No Render/production access, real keys/data, bank/Telegram/SMS/Wialon connections, system trust-store modification, PostgreSQL or native-driver concurrency claims. No external listener or general egress is authorized.
- The loopback HTTP backend is intentionally private to this local simulation, not an exposed plaintext user-login service. The harness forbids credential-bearing direct client HTTP; deployment ingress/firewall/HSTS behavior is a separate gate. It does not introduce or require an application `request.is_secure` bypass behind the terminating proxy.
- A full application RED is not repaired here. Named assertions and exception stack-frame locations are preserved without credential-bearing response/request dumps. Setup/cleanup failures are distinct from assertion REDs. When an early assertion stops a named multi-assertion case, later assertions within that case are **not** claimed as covered by that receipt.
