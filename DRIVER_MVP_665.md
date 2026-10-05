# Driver MVP — car 665

Added a test-only driver portal at `/driver`.

Features:
- uses existing rental calculation logic;
- shows car 665, driver, daily rent, current rent due and separate driver debt;
- stores test top-ups in `driver_wallet_transactions`;
- shows net balance and top-up history;
- test buttons: 1,857 / 5,000 / 13,000 RUB;
- API is restricted to car 665 by default (`DRIVER_MVP_CAR`).

No bank or Wialon integration is enabled yet. Test top-ups do not move real money and do not change Wialon state.
