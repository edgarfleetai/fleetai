"""Read-only Wialon client: login with a token and list units with last position.

Only token/login and core/search_items are ever called. No vehicle commands.
"""
import json
import os

import requests

ALLOWED_SERVICES = frozenset({"token/login", "core/search_items"})


def _call(svc, params, sid=None):
    if svc not in ALLOWED_SERVICES:
        raise ValueError("Wialon service not allowed in the dashboard: " + svc)
    base = os.environ.get("WIALON_BASE_URL", "https://wialonreg.ru").rstrip("/")
    url = os.environ.get("WIALON_API_URL", base + "/wialon/ajax.html")
    payload = {"svc": svc, "params": json.dumps(params, ensure_ascii=False)}
    if sid:
        payload["sid"] = sid
    response = requests.get(url, params=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def parse_units(items):
    units = []
    for item in items or []:
        pos = item.get("pos") or {}
        lat, lon = pos.get("y"), pos.get("x")
        ok = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        units.append({
            "id": item.get("id"), "name": item.get("nm", ""),
            "lat": lat if ok else None, "lon": lon if ok else None,
            "speed_kmh": pos.get("s") if ok else None, "course": pos.get("c") if ok else None,
            "time": pos.get("t") if ok else None,
        })
    return units


def fetch_units(call=None):
    """Return (units, error_message)."""
    call = call or _call
    token = (os.environ.get("WIALON_TOKEN") or "").strip()
    if not token:
        return [], "WIALON_TOKEN не задан"
    try:
        login = call("token/login", {"token": token})
        sid = login.get("eid") if isinstance(login, dict) and login.get("error") is None else None
        if not sid:
            return [], "Wialon: не удалось войти по токену"
        found = call("core/search_items", {
            "spec": {"itemsType": "avl_unit", "propName": "sys_name", "propValueMask": "*",
                     "sortType": "sys_name", "propType": "property", "or_logic": False},
            "force": 1, "flags": 1 | 1024, "from": 0, "to": 0,
        }, sid=sid)
        if not isinstance(found, dict) or found.get("error") is not None:
            return [], "Wialon: ошибка поиска объектов"
        return parse_units(found.get("items")), None
    except requests.RequestException:
        return [], "Wialon недоступен"
