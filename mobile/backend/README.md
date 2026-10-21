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
