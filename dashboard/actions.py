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


# ---- Editing and deleting journal operations -------------------------------
TOPUP_MARK = "[DRIVER_TOPUP:"
EDITABLE_IN_PLACE = ("repair", "service", "expense")


def call_view(app, fname, path, payload, views=None, **kwargs):
    """Run one old FleetAI handler in a fresh request context; return (status, body)."""
    if views is None:
        import fleetai.routes as views
    with app.test_request_context(path, method="POST", json=payload):
        rv = getattr(views, fname)(**kwargs)
    status = 200
    if isinstance(rv, tuple):
        rv, status = rv[0], rv[1]
    body = json.loads(rv.get_data(as_text=True)) if hasattr(rv, "get_data") else dict(rv)
    if not body.get("ok", status < 400) and status < 400:
        status = 400
    return status, body


def load_operation(engine, op_id):
    from sqlalchemy import text
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, date, car_code, type, category, description, amount, raw_message "
                                "FROM operations WHERE id = :i"), {"i": int(op_id)}).mappings().first()
    return dict(row) if row else None


def _reverse_topup(op):
    """The old delete handler removes the income but not the wallet credit of a
    driver top-up; write the matching correction so the wallet stays right."""
    from datetime import datetime
    from fleetai import db as fleet_db
    from fleetai.models import Car, DriverWalletTransaction
    with fleet_db.Session() as s:
        car = s.query(Car).filter(Car.code == str(op["car_code"]).strip()).first()
        s.add(DriverWalletTransaction(
            driver_name=(car.driver if car else "") or "", car_code=str(op["car_code"]).strip(),
            amount=-int(op["amount"] or 0), transaction_type="correction", source="dashboard",
            comment=f"Отмена пополнения (операция #{op['id']})", date=datetime.now()))
        s.commit()


def _once(key, fn):
    now = time.time()
    with _lock:
        if key in _done:
            st, body = _done[key][1]
            return st, dict(body, message=(body.get("message") or "") + " (повторное нажатие не записано)")
        _done[key] = (now, (409, {"ok": False, "message": "Выполняется"}))
    try:
        status, body = fn()
    except Exception as error:
        status, body = 500, {"ok": False, "message": f"Ошибка: {type(error).__name__}"}
    with _lock:
        if status < 400:
            _done[key] = (now, (status, body))
        else:
            _done.pop(key, None)
    return status, body


def delete_operation(app, engine, op_id, key, views=None):
    op = load_operation(engine, op_id)
    if not op:
        return 404, {"ok": False, "message": "Операция не найдена"}

    def run():
        status, body = call_view(app, "api_delete_operation", f"/api/delete-operation/{op_id}", {},
                                 views=views, operation_id=int(op_id))
        if status < 400 and TOPUP_MARK in (op["raw_message"] or ""):
            _reverse_topup(op)
            body = dict(body, message=body.get("message", "") + " Кошелёк водителя уменьшен на эту сумму.")
        return status, body
    return _once("del:" + key, run)


def edit_operation(app, engine, op_id, data, key, views=None, save=None):
    """Repairs/expenses: the old edit handler (same id). Driver top-ups: cancel
    and top up again with the new amount. Other operations: save the corrected
    command, then delete the old record."""
    op = load_operation(engine, op_id)
    if not op:
        return 404, {"ok": False, "message": "Операция не найдена"}
    from . import ops as ops_mod

    def run():
        if TOPUP_MARK in (op["raw_message"] or ""):
            amount = int(str(data.get("amount") or "0").replace(" ", "") or 0)
            if amount <= 0:
                return 400, {"ok": False, "message": "Укажите новую сумму"}
            st, body = call_view(app, "api_delete_operation", f"/api/delete-operation/{op_id}", {},
                                 views=views, operation_id=int(op_id))
            if st >= 400:
                return st, body
            _reverse_topup(op)
            return call_view(app, "api_driver_wallet_topup", "/api/driver-wallet/topup",
                             {"car_code": str(op["car_code"]).strip(), "amount": amount,
                              "payment_method": data.get("payment_method") or "cash",
                              "comment": f"Исправление операции #{op_id}"}, views=views)
        message = str(data.get("message") or "").strip()[:ops_mod.MAX_LEN]
        if not message:
            return 400, {"ok": False, "message": "Введите исправленную команду"}
        if op["type"] in EDITABLE_IN_PLACE:
            return call_view(app, "api_edit_operation", f"/api/edit-operation/{op_id}",
                             {"message": message, "date": str(data.get("date") or "")}, views=views,
                             operation_id=int(op_id))
        ok, results = ops_mod.commit(message, "edit:" + key, engine, save=save)
        if not ok:
            return 400, {"ok": False, "message": " · ".join(r.get("message", "") for r in results)}
        st, body = call_view(app, "api_delete_operation", f"/api/delete-operation/{op_id}", {},
                             views=views, operation_id=int(op_id))
        if st >= 400:
            return st, {"ok": False, "message": "Новая запись сохранена, но старую удалить не удалось: " + body.get("message", "")}
        return 200, {"ok": True, "message": "Исправлено: " + " · ".join(r.get("message", "") for r in results)}
    return _once("edit:" + key, run)
