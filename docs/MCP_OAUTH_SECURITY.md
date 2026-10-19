# FleetAI staging MCP — OAuth security contract

Status: **NOT IMPLEMENTED / DO NOT CONNECT TO CHATGPT**.

The staging MCP endpoint is read-only, and currently accepts a separately
configured static bearer token. This is not OAuth. The protected-resource
metadata endpoint fails closed until FLEETAI_MCP_OAUTH_ISSUER is configured;
setting that variable alone does **not** make OAuth functional.

## Required before enabling OAuth

1. Use a trusted OAuth 2.1 authorization server (or an audited OAuth library),
   not a handwritten authorization-code/token implementation.
2. Configure a dedicated staging-only issuer using HTTPS. Publish the
   authorization-server metadata and protected-resource metadata; validate
   issuer, audience/resource, token expiration, scope and signature (or
   introspection), including key rotation and revocation.
3. Authorization-code flow with PKCE S256 and exact registered redirect URI
   matching. No wildcard callbacks, no implicit flow, no password grant.
4. Only the FleetAI staging owner can consent; authenticate via existing owner
   session, use explicit consent and CSRF protection. No auto-consent based
   solely on knowledge of a client_id.
5. Restrict tokens to `fleetai:read` and the staging MCP resource. Enforce
   access on **every** MCP request; deny access on all missing, expired,
   invalid, wrong-audience, or insufficient-scope tokens.
6. Keep production disabled. Staging lockdown must remain active for all
   mutations; MCP tools must not issue writes.
7. Never store OAuth secrets or access tokens in GitHub or expose them to
   frontend JavaScript. Use Render secret environment variables.
8. Cover negative paths: invalid PKCE, redirect mismatch, forged state,
   reused code, expired/revoked token, scope escalation, wrong audience,
   cross-origin request, unauthenticated owner, token replay, and accidental
   production exposure.
9. Verify real ChatGPT MCP OAuth handshake end-to-end with an owner test
   account before advertising the connector as ready.

## Current API

- POST /mcp: protected by a static staging-only bearer token.
- GET /.well-known/oauth-protected-resource
- GET /.well-known/oauth-protected-resource/mcp

The discovery endpoints advertise the issuer only when configured. The
static bearer token must be replaced by token validation before enabling
OAuth; do not simply accept both credential types without explicit controls.
