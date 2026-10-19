"""Validate staging-only OAuth access tokens from a trusted external issuer.

This module is a resource-server verifier, NOT an OAuth authorization server.
All issuer/JWKS settings are server-side secrets/configuration on Render.
"""
import os
from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient


@lru_cache(maxsize=4)
def _jwks_client(jwks_uri):
    return PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=300, timeout=5)


def oauth_enabled():
    return bool(os.getenv("FLEETAI_MCP_OAUTH_ISSUER", "").strip())


def validate_access_token(token):
    """Fail closed on missing configuration, invalid JWT or missing read scope."""
    issuer = os.getenv("FLEETAI_MCP_OAUTH_ISSUER", "").strip().rstrip("/")
    jwks_uri = os.getenv("FLEETAI_MCP_OAUTH_JWKS_URI", "").strip()
    audience = os.getenv("FLEETAI_MCP_OAUTH_AUDIENCE", "").strip()
    if not issuer or not jwks_uri or not audience or not token:
        return False
    issuer_parts, jwks_parts = urlsplit(issuer), urlsplit(jwks_uri)
    if (issuer_parts.scheme != "https" or not issuer_parts.netloc
            or issuer_parts.username or issuer_parts.password or issuer_parts.query
            or issuer_parts.fragment or jwks_parts.scheme != "https"
            or jwks_parts.netloc != issuer_parts.netloc or jwks_parts.username
            or jwks_parts.password or jwks_parts.fragment):
        return False
    try:
        signing_key = _jwks_client(jwks_uri).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["RS256", "ES256"],
            issuer=issuer, audience=audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
        scopes = claims.get("scope", "")
        if not isinstance(scopes, str):
            return False
        return "fleetai:read" in scopes.split()
    except (jwt.PyJWTError, ValueError, TypeError, OSError):
        return False
