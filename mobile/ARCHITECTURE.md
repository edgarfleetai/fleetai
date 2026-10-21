# Klever Park mobile architecture

- `klever-driver/`: React Native / Expo app, standalone from existing driver web portal.
- `backend/`: isolated Flask API scaffold. Do not deploy with FleetAI production.
- Production FleetAI data is **not** available through this scaffold. Integrate via a separate authenticated least-privilege API after a security review.
- Identity: SMS OTP with throttling, server-issued revocable sessions, separate KYC workflow; no raw passport images in analytics or logs.
- Verification: provider-hosted secure capture preferred; explicit consent and Russian personal-data/biometric compliance review before activation.
- Fleet: availability derived from trusted backend; booking transaction must atomically lock vehicle, expire reservations, and require approved verification.
- Money: payments via provider-hosted checkout and signed webhook; never trust client balance or a success redirect.
- Drivers: strict per-user authorization, explicit admin reconciliation of existing driver identities, no match solely by car number or name.
- Before release: tests, staging, secret management, retention/deletion policies, incident procedures, manual UAT and app-store accounts.
