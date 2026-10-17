"""Server-side authentication helper for privileged dispatcher actions.

Integration with routes is intentionally a separate change. Never expose credentials
in URL query strings, logs, or client-side JavaScript.
"""
import hashlib
import hmac
import os


def verify_admin_key(provided: str | None) -> bool:
    """Fail closed when no key is configured; constant-time digest comparison."""
    expected = os.environ.get("FLEETAI_ADMIN_API_KEY", "")
    if not expected or not provided:
        return False
    actual_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(actual_digest, expected_digest)
