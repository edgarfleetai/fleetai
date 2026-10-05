import os
import requests


TBANK_TOKEN = os.getenv("TBANK_TOKEN", "")
TBANK_API_URL = "https://business.tbank.ru/openapi/api/v1"


def _headers():
    if not TBANK_TOKEN:
        raise RuntimeError("Переменная TBANK_TOKEN не задана в Render")

    return {
        "Authorization": f"Bearer {TBANK_TOKEN}",
        "Accept": "application/json",
    }


def get_accounts():
    response = requests.get(
        f"{TBANK_API_URL}/bank-accounts",
        headers=_headers(),
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"T-Bank API error {response.status_code}: {response.text}"
        )

    return response.json()
