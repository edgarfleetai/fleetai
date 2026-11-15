"""Owner actions that already exist in the old FleetAI, run through the old
FleetAI's own handlers so the records are identical:

  topup         /api/driver-wallet/topup     пополнить кошелёк водителя
  fine          /api/driver-wallet/fine      штраф водителю
  assign        /api/driver-assignment       назначить / сменить водителя
  add_car       /api/add-car                 добавить машину
  close_period  /api/close-period/<code>     закрыть расчётный период

Only whitelisted fields are passed; the handler runs inside a fresh request
context, so it never sees the dashboard's cookies or headers.
"""
import threading
import time

from flask import json

from .data import RETIRED_CODES

ACTIONS = {
    "topup": ("api_driver_wallet_topup", "/api/driver-wallet/topup",
              ("car_code", "amount", "payment_method", "comment")),
    "fine": ("api_driver_wallet_fine", "/api/driver-wallet/fine",
             ("car_code", "amount", "reason", "comment")),
    "assign": ("api_driver_assignment_save", "/api/driver-assignment",
               ("car_code", "driver", "start_date", "daily_rent", "opening_balance")),
    "add_car": ("api_add_car", "/api/add-car",
                ("code", "brand", "model", "plate", "year", "purchase_date", "purchase_price", "mileage",
                 "owner_type", "investor_name", "investor_percent", "settlement_day")),
    "close_period": ("api_close_period", "/api/close-period/{code}", ("car_code",)),
}

_done = {}
_lock = threading.Lock()


def _clean(name, payload):
    fields = ACTIONS[name][2]
    out = {}
    for k in fields:
        v = payload.get(k)
        if v is None:
            continue
        out[k] = str(v).strip()[:300] if not isinstance(v, (int, float)) else v
    return out


def run(app, name, payload, key, views=None):
    """Return (http_status, body). Idempotent per key for one hour."""
    if name not in ACTIONS:
        return 404, {"ok": False, "message": "Неизвестное действие"}
    clean = _clean(name, payload or {})
    code = str(clean.get("car_code") or clean.get("code") or "").strip()
    if code in RETIRED_CODES:
        return 400, {"ok": False, "message": f"Машины {code} больше нет: она ездит как {RETIRED_CODES[code]}"}
    now = time.time()
    with _lock:
        for k in [k for k, (t, _) in _done.items() if now - t > 3600]:
            _done.pop(k, None)
        if key in _done:
            st, body = _done[key][1]
            return st, dict(body, message=(body.get("message") or "") + " (повторное нажатие не записано)")
        _done[key] = (now, (409, {"ok": False, "message": "Выполняется"}))
    try:
        if views is None:
            import fleetai.routes as views
        fname, path, _ = ACTIONS[name]
        view = getattr(views, fname)
        kwargs = {"code": code} if name == "close_period" else {}
        with app.test_request_context(path.format(code=code), method="POST", json=clean):
            rv = view(**kwargs)
        status = 200
        if isinstance(rv, tuple):
            rv, status = rv[0], rv[1]
        body = json.loads(rv.get_data(as_text=True)) if hasattr(rv, "get_data") else dict(rv)
        if not body.get("ok", status < 400) and status < 400:
            status = 400
    except Exception as error:  # never leave the key "in progress"
        status, body = 500, {"ok": False, "message": f"Ошибка: {type(error).__name__}"}
    with _lock:
        if status < 400:
            _done[key] = (now, (status, body))
        else:
            _done.pop(key, None)
    return status, body
