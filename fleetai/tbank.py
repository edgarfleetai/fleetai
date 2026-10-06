import os
import uuid
import hashlib
from datetime import datetime, timedelta, timezone

import certifi
import requests


TBANK_TOKEN = os.getenv("TBANK_TOKEN", "")
TBANK_ACCOUNT_NUMBER = os.getenv("TBANK_ACCOUNT_NUMBER", "40802810300009284135")
TBANK_API_URL = "https://business.tbank.ru/openapi/api/v1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CA_BUNDLE = os.path.join(BASE_DIR, "Russian_Trusted_CA.pem")
ACQUIRING_CA_BUNDLE = os.path.join(BASE_DIR, "combined_ca.pem")


def _headers():
    if not TBANK_TOKEN:
        raise RuntimeError("Переменная TBANK_TOKEN не задана в Render")
    return {
        "Authorization": f"Bearer {TBANK_TOKEN}",
        "Accept": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }


def _check_ca():
    if not os.path.exists(CA_BUNDLE):
        raise RuntimeError(f"Не найден сертификат T-Bank: {CA_BUNDLE}")


def _get_acquiring_ca_bundle():
    _check_ca()
    with open(certifi.where(), "rb") as system_ca:
        system_data = system_ca.read()
    with open(CA_BUNDLE, "rb") as russian_ca:
        russian_data = russian_ca.read()
    with open(ACQUIRING_CA_BUNDLE, "wb") as combined:
        combined.write(system_data)
        combined.write(b"\\n")
        combined.write(russian_data)
    return ACQUIRING_CA_BUNDLE


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
            f"T-Bank API error {response.status_code}: {response.text}"
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
            f"T-Bank statement error {response.status_code}: {response.text}"
        )
    return response.json()


# ============================================================
# T-BANK INTERNET ACQUIRING
# ============================================================

TBANK_TERMINAL_KEY = os.getenv("TBANK_EACQ_TERMINAL_KEY", "")
TBANK_TERMINAL_PASSWORD = os.getenv("TBANK_EACQ_PASSWORD", "")
TBANK_ACQUIRING_URL = "https://securepay.tinkoff.ru/v2"


def _acquiring_token(payload):
    if not TBANK_TERMINAL_KEY:
        raise RuntimeError("TBANK_EACQ_TERMINAL_KEY не задан в Render")
    if not TBANK_TERMINAL_PASSWORD:
        raise RuntimeError("TBANK_EACQ_PASSWORD не задан в Render")

    token_data = {}
    for key, value in payload.items():
        if key == "Token":
            continue
        if isinstance(value, (dict, list)):
            continue
        token_data[key] = value

    token_data["Password"] = TBANK_TERMINAL_PASSWORD
    token_string = "".join(
        str(token_data[key]) for key in sorted(token_data.keys())
    )
    return hashlib.sha256(token_string.encode("utf-8")).hexdigest()


def create_payment(amount_rubles, order_id, description="Оплата аренды автомобиля"):
    if not TBANK_TERMINAL_KEY:
        raise RuntimeError("TBANK_EACQ_TERMINAL_KEY не задан в Render")

    amount_kopecks = int(round(float(amount_rubles) * 100))
    if amount_kopecks <= 0:
        raise ValueError("Сумма платежа должна быть больше 0")

    payload = {
    "TerminalKey": TBANK_TERMINAL_KEY,
    "Amount": amount_kopecks,
    "OrderId": str(order_id),
    "Description": description,

    # После успешной оплаты вернуть водителя в его кабинет
    "SuccessURL": "https://fleetai-1.onrender.com/driver?payment=success",

    # После неуспешной оплаты тоже вернуть в кабинет
    "FailURL": "https://fleetai-1.onrender.com/driver?payment=failed",
}
    payload["Token"] = _acquiring_token(payload)

    response = requests.post(
        f"{TBANK_ACQUIRING_URL}/Init",
        json=payload,
        timeout=30,
        verify=_get_acquiring_ca_bundle(),
    )
    if not response.ok:
        raise RuntimeError(
            f"T-Bank acquiring HTTP error {response.status_code}: {response.text}"
        )

    result = response.json()
    if not result.get("Success"):
        raise RuntimeError("T-Bank acquiring error: " + str(result))
    return result


def create_sbp_link(payment_id):
    """
    Получает ссылку СБП для уже созданного платежа T-Банка.
    Существующую логику create_payment и webhook не изменяет.
    """
    if not TBANK_TERMINAL_KEY:
        raise RuntimeError("TBANK_EACQ_TERMINAL_KEY не задан в Render")

    payload = {
        "TerminalKey": TBANK_TERMINAL_KEY,
        "PaymentId": str(payment_id),
        "DataType": "PAYLOAD",
        "PaymentMethod": "SBP",
    }
    payload["Token"] = _acquiring_token(payload)

    response = requests.post(
        f"{TBANK_ACQUIRING_URL}/GetQr",
        json=payload,
        timeout=30,
        verify=_get_acquiring_ca_bundle(),
    )
    if not response.ok:
        raise RuntimeError(
            f"T-Bank GetQr HTTP error {response.status_code}: {response.text}"
        )

    result = response.json()
    if not result.get("Success"):
        raise RuntimeError("T-Bank GetQr error: " + str(result))

    payment_url = str(result.get("Data") or "").strip()
    if not payment_url:
        raise RuntimeError("T-Bank GetQr не вернул ссылку СБП")

    return payment_url


def verify_notification(data):
    """
    Проверяет Token входящего уведомления T-Банка.
    """

    if not TBANK_TERMINAL_PASSWORD:
        raise RuntimeError(
            "TBANK_EACQ_PASSWORD не задан в Render"
        )

    received_token = str(data.get("Token") or "")

    if not received_token:
        return False

    token_data = {}

    for key, value in data.items():

        # Token самого уведомления в подпись не входит
        if key == "Token":
            continue

        # Вложенные объекты/массивы в подпись не входят
        if isinstance(value, (dict, list)):
            continue

        # null не участвует
        if value is None:
            continue

        # ВАЖНО:
        # JSON true/false должны остаться true/false,
        # а не Python True/False
        if isinstance(value, bool):
            value = "true" if value else "false"

        token_data[key] = str(value)

    # Добавляем пароль терминала
    token_data["Password"] = TBANK_TERMINAL_PASSWORD

    # Сортировка по ключам + склейка значений
    token_string = "".join(
        token_data[key]
        for key in sorted(token_data.keys())
    )

    expected_token = hashlib.sha256(
        token_string.encode("utf-8")
    ).hexdigest()

    return expected_token.lower() == received_token.lower()
