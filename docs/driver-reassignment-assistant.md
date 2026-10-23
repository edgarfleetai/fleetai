# Driver reassignment assistant — design

A driver move is always a draft first. The user identifies the source and target cars. Read current assignments and show the before/after state. Reject an occupied target unless the user explicitly requests a swap. Never infer a swap from a simple move.

Before commit, require owner authentication, session-bound CSRF validation, explicit user confirmation and an idempotency key. Re-read and lock both vehicle rows in one database transaction; reject if either assignment changed since preview. Update both assignments atomically and append an audit event with actor, timestamp, old and new assignments. Do not change driver debt, deposit, rent history or payment obligations implicitly. Warn about outstanding settlements and request a separate operation when needed.

Voice examples: 'Move Merdan from 636 to 404' and 'Swap drivers between 636 and 404'. For ambiguous driver names or car codes, ask a clarifying question instead of guessing.

On iPhone, a Shortcut captures dictated text and sends it to a protected draft endpoint. A confirmation web page shows the preview; the Shortcut alone must not execute a write. The staging environment remains read-only until explicit safe write testing is approved.
