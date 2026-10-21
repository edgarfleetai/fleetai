# Isolated Klever Driver API

This is an intentionally safe API scaffold, **not a functional registration or booking backend**.

Run locally:

```bash
pip install -r requirements.txt
python -m unittest -v test_app
gunicorn app:app
```

Endpoints: GET /health, GET /v1/public/vehicles (empty until integrated), POST /v1/auth/otp/request, POST /v1/auth/otp/verify, POST /v1/bookings, POST /v1/verification (all return 503 until implemented).

No connection to production database, no customer records, no secrets, no fake success responses.

## Account and session module

`identity.py` provides isolated SQL account records, E.164 phone validation, revocable random bearer sessions stored as SHA-256 hashes, and explicit admin-controlled FleetAI identity mapping. These functions are **not HTTP endpoints** and cannot register anyone without a trusted, server-side OTP confirmation. The current `/v1/auth/*` routes continue to return HTTP 503. Session and account data must be moved to a managed, access-controlled database before launch.

`booking.py` demonstrates SQLite atomic reservations with an expiry and verified-driver gate. It is **not yet wired to HTTP or FleetAI**, and PostgreSQL transactions/advisory locks plus fleet status reconciliation must be implemented for deployment.

Run `python -m unittest discover -v -p 'test_*.py'` for all backend tests.
