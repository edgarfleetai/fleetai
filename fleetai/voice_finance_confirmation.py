"""Short-lived signed finance preview; never authorizes without owner session."""
import base64
import hashlib
import hmac
import json
import time


def _b64(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _unb64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def sign_finance_preview(secret, draft, *, now=None):
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError('Confirmation secret unavailable')
    timestamp = int(time.time() if now is None else now)
    payload = _b64(json.dumps({'draft': draft, 'exp': timestamp + 300},
                               ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + '.' + signature


def verify_finance_preview(secret, token, *, now=None):
    if not isinstance(secret, str) or len(secret) < 32 or not isinstance(token, str) or len(token) > 4096 or token.count('.') != 1:
        return None
    try:
        payload, signature = token.split('.')
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        value = json.loads(_unb64(payload))
        current = int(time.time() if now is None else now)
        if type(value.get('exp')) is not int or not current < value['exp'] <= current + 300:
            return None
        return value['draft'] if isinstance(value.get('draft'), dict) else None
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
