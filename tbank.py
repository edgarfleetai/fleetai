import os
import requests


TBANK_BASE_URL = "https://business.tbank.ru/openapi/api/v1"


def _headers():
    token = os.getenv("TBANK_TOKEN", "").strip()

    if not token:
        raise RuntimeError(
            "Переменная TBANK_TOKEN не найдена в Render"
        )

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def get_accounts():
    """
    Тест подключения к T-Банку.
    Получает список счетов, доступных токену.
    Никаких платежей не создаёт.
    """

    response = requests.get(
        f"{TBANK_BASE_URL}/bank-accounts",
        headers=_headers(),
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"T-Bank API error {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()
