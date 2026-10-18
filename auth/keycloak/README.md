# FleetAI Keycloak — staging only

This is a deployment template, not an active OAuth connection. **Never** use
the production FleetAI database for Keycloak.

## Render setup

Create a **separate PostgreSQL database** for Keycloak and a separate Render
Docker web service using:

- Repository: `edgarfleetai/fleetai`
- Branch: `feature/admin-topup-guard`
- Dockerfile: `auth/keycloak/Dockerfile`
- Plan: Keycloak needs sufficient RAM; confirm plan/cost before provisioning.

Required environment variables (set in Render, never commit real values):

- `KC_DB=postgres`
- `KC_DB_URL=jdbc:postgresql://<KEYCLOAK_DB_HOST>:5432/<DB_NAME>`
- `KC_DB_USERNAME=<KEYCLOAK_DB_USER>`
- `KC_DB_PASSWORD=<KEYCLOAK_DB_PASSWORD>`
- `KC_HOSTNAME=https://<KEYCLOAK_PUBLIC_HOSTNAME>`
- `KC_BOOTSTRAP_ADMIN_USERNAME=<ADMIN_USERNAME>`
- `KC_BOOTSTRAP_ADMIN_PASSWORD=<LONG_RANDOM_SECRET>`

Only allow access through HTTPS. Do not start the server until all values are
configured. Never reuse FleetAI's admin password or database credentials.

## Configure OAuth

1. Create a realm `fleetai-staging`; require strong admin credentials and
   use MFA for the Keycloak admin account.
2. Create a dedicated owner identity; disable open user self-registration.
3. Register the ChatGPT MCP client using its **actual displayed callback URI**.
   Do not guess callback addresses or use wildcard redirects.
4. Use Authorization Code + PKCE S256, no implicit/direct grants. Set the
   audience of issued access tokens to the exact staging MCP resource URL.
5. Configure a `fleetai:read` scope, assign only to the owner and client.
6. Verify JWT signature against the realm JWKS and issuer, expiry, audience,
   subject, and read scope. Test the actual Keycloak token claims: Keycloak
   often emits scopes differently and does not automatically add a resource
   audience claim.
7. Set the following on the **staging FleetAI service only**, after the
   issuer/JWKS/audience and claim mappings are verified:
   `FLEETAI_MCP_OAUTH_ISSUER`,
   `FLEETAI_MCP_OAUTH_JWKS_URI`,
   `FLEETAI_MCP_OAUTH_AUDIENCE`.
8. Confirm that static MCP bearer credentials are rejected in OAuth mode.
   Test denial of anonymous, expired, wrong-audience and insufficient-scope
   tokens, and successful owner-only read access.

## Caution

The current FleetAI MCP integration does **not** yet implement ChatGPT client
registration, OAuth consent, or full end-to-end verification. The presence of
this Dockerfile does not mean the connector is ready.
