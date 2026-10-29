"""Minimal short-lived scoped token for read-only mobile voice previews.

Tokens are signed with an independently provisioned secret. Never use Flask
session secrets as mobile API credentials.
"""
import base64
import hashlib
import hmac
import json
import time


ALLOWED_SCOPES = frozenset({'driver:lookup', 'driver-move:preview'})


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(data):
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))


def issue_mobile_token(secret, scope, *, ttl_seconds=300, now=None):
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError('Mobile signing secret is not configured')
    if scope not in ALLOWED_SCOPES or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
        raise ValueError('Invalid scope or TTL')
    timestamp = int(time.time() if now is None else now)
    payload = _b64(json.dumps({'scope': scope, 'exp': timestamp + ttl_seconds},
                              separators=(',', ':'), sort_keys=True).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + '.' + signature


def verify_mobile_token(secret, token, required_scope, *, now=None):
    if not isinstance(secret, str) or len(secret) < 32 or required_scope not in ALLOWED_SCOPES:
        return False
    if not isinstance(token, str) or len(token) > 2048 or token.count('.') != 1:
        return False
    try:
        payload, signature = token.split('.')
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return False
        data = json.loads(_unb64(payload))
        current = int(time.time() if now is None else now)
        return (data.get('scope') == required_scope and type(data.get('exp')) is int
                and current < data['exp'] <= current + 900)
    except (ValueError, TypeError, UnicodeDecodeError, KeyError):
        return False
