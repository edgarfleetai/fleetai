import os
import uuid
from datetime import datetime, timedelta, timezone

import requests


TBANK_TOKEN = os.getenv("TBANK_TOKEN", "")
TBANK_ACCOUNT_NUMBER = os.getenv(
    "TBANK_ACCOUNT_NUMBER",
    "40802810300009284135",
)

TBANK_API_URL = "https://business.tbank.ru/openapi/api/v1"

CA_BUNDLE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Russian_Trusted_CA.pem",
)


def _headers():
    if not TBANK_TOKEN:
        raise RuntimeError(
            "Переменная TBANK_TOKEN не задана в Render"
        )

    return {
        "Authorization": f"Bearer {TBANK_TOKEN}",
        "Accept": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }


def _check_ca():
    if not os.path.exists(CA_BUNDLE):
        raise RuntimeError(
            f"Не найден сертификат T-Bank: {CA_BUNDLE}"
        )


def get_accounts():
    _check_ca()

    response = requests.get(
        f"{TBANK_API_URL}/bank-accounts",
        headers=_headers(),
        timeout=20,
        verify=CA_BUNDLE,
    )

    if not response.ok:
        raise RuntimeError(
            f"T-Bank API error "
            f"{response.status_code}: {response.text}"
        )

    return response.json()


def get_statement(days=7):
    _check_ca()

    now = datetime.now(timezone.utc)
    date_from = now - timedelta(days=days)

    params = {
        "accountNumber": TBANK_ACCOUNT_NUMBER,
        "from": date_from.isoformat(),
        "to": now.isoformat(),
        "operationStatus": "Transaction",
        "limit": 100,
        "withBalances": "true",
    }

    response = requests.get(
        f"{TBANK_API_URL}/statement",
        headers=_headers(),
        params=params,
        timeout=30,
        verify=CA_BUNDLE,
    )

    if not response.ok:
        raise RuntimeError(
            f"T-Bank statement error "
            f"{response.status_code}: {response.text}"
        )

    return response.json()
