# iPhone Shortcuts: preview a driver move (development only)

This workflow is **not deployed**. Do not point Shortcuts at production until reviewed and explicitly approved.

1. Create a new iOS Shortcut named `FleetAI — водители`.
2. Add **Dictate Text** (Russian), or **Ask for Input** with Text input.
3. Add **Get Contents of URL**: `https://YOUR-TEST-HOST/api/assistant/driver-move/preview`.
4. Set Method to **POST**, Request Body to **JSON**, key `text` set to the dictated text.
5. Add **Get Dictionary Value**, key `mobile_summary`, then another **Get Dictionary Value**, key `message`.
6. Add **Show Result** (or **Speak Text**) with that message.

Example command: `Поменяй водителей 404 и 636 местами`.

## Authentication and safety

This endpoint is protected by the existing FleetAI admin session and CSRF/origin checks. A bare Shortcut HTTP request is **not authenticated** and should be rejected. **Do not** paste administrator cookies, CSRF secrets, passwords or bearer tokens into a Shortcut, or expose this route publicly to make it work. An authenticated mobile integration with short-lived, narrowly scoped credentials is required before this can function outside the logged-in web app.

The endpoint returns a read-only preview; no driver is reassigned. Financial closeout must be completed separately, and a confirmed execution endpoint is not yet available. The iPhone Shortcut should never report that a driver has been moved.
