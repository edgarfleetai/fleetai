import os
import requests


TBANK_TOKEN = os.getenv("TBANK_TOKEN", "")

TBANK_API_URL = "https://business.tbank.ru/openapi/api/v1"

# Russian_Trusted_CA.pem лежит в той же папке, что и tbank.py
CA_BUNDLE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Russian_Trusted_CA.pem",
)


def _headers():
    if not TBANK_TOKEN:
        raise RuntimeError("Переменная TBANK_TOKEN не задана в Render")

    return {
        "Authorization": f"Bearer {TBANK_TOKEN}",
        "Accept": "application/json",
    }


def get_accounts():
    if not os.path.exists(CA_BUNDLE):
        raise RuntimeError(
            f"Не найден сертификат T-Bank: {CA_BUNDLE}"
        )

    response = requests.get(
        f"{TBANK_API_URL}/bank-accounts",
        headers=_headers(),
        timeout=20,
        verify=CA_BUNDLE,
    )

    if not response.ok:
        raise RuntimeError(
            f"T-Bank API error {response.status_code}: {response.text}"
        )

    return response.json()
from datetime import datetime, timedelta, timezone
import uuid


def get_statement(days=7):
    account_number = "40802810300009284135"

    now = datetime.now(timezone.utc)
    date_from = now - timedelta(days=days)

    url = f"{BASE_URL}/api/v1/statement"

    params = {
        "accountNumber": account_number,
        "from": date_from.isoformat(),
        "to": now.isoformat(),
        "operationStatus": "Transaction",
        "limit": 100,
        "withBalances": "true",
    }

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    return response.json()
