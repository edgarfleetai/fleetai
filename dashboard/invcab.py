"""Investor cabinet: an investor watches the results of his cars, read only (owner's idea, 19.11.2026).

Access works like the driver cabinet:
- the owner issues a personal link (``/i#token=…``): single use, valid 7 days;
- opening it gives a session cookie for 180 days on that device;
- the owner can close all access of an investor at once ("Закрыть доступ").

Links and sessions live in a new additive table ``dashboard_investor_access``
(only token hashes are stored). Nothing else in the database is written: the
investor only reads his short report - per car received / expenses / profit /
share, the owner's explanations, what the money was spent on, payouts - and can
download the same PDF the owner sends. Internal checks, raw operation texts of
income and other investors' cars are never shown.
"""
import hmac
import secrets
import time
from hashlib import sha256
from urllib.parse import quote

from flask import abort, jsonify, request, send_file
from sqlalchemy import Column, Float, MetaData, String, Table, func, inspect, select

COOKIE = "__Host-fa4i"
LINK_TTL = 7 * 86400
SESSION_TTL = 180 * 86400

meta = MetaData()
access = Table(
    "dashboard_investor_access", meta,
    Column("token_hash", String(64), primary_key=True),
    Column("kind", String(10), nullable=False),          # link | session
    Column("investor", String(20), nullable=False),
    Column("csrf_token", String(64), nullable=False, default=""),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("consumed_at", Float),
    Column("revoked_at", Float),
)


def _hash(raw):
    return sha256(raw.encode("utf-8")).hexdigest()


def _engine():
    from fleetai import db as fleet_db
    return fleet_db.engine


def _ready(eng):
    return inspect(eng).has_table("dashboard_investor_access")


def issue_link(investor):
    eng = _engine()
    meta.create_all(eng, checkfirst=True)
    raw, now = secrets.token_urlsafe(32), time.time()
    with eng.begin() as c:
        c.execute(access.insert().values(token_hash=_hash(raw), kind="link", investor=investor, csrf_token="",
                                         created_at=now, expires_at=now + LINK_TTL))
    return raw


def status(investor):
    eng, now = _engine(), time.time()
    if not _ready(eng):
        return {"sessions": 0, "pending_links": 0}
    with eng.connect() as c:
        def n(kind, extra=True):
            return c.execute(select(func.count()).select_from(access).where(
                access.c.investor == investor, access.c.kind == kind, access.c.revoked_at.is_(None),
                access.c.expires_at > now, extra)).scalar() or 0
        return {"sessions": n("session"), "pending_links": n("link", access.c.consumed_at.is_(None))}


def revoke_all(investor):
    eng = _engine()
    if not _ready(eng):
        return 0
    with eng.begin() as c:
        return c.execute(access.update().where(access.c.investor == investor, access.c.revoked_at.is_(None))
                         .values(revoked_at=time.time())).rowcount


def public_report(report, notes, car_info):
    """Only what the investor may see; amounts in kopecks."""
    T = report.get("total") or {}
    fixed = (T.get("gps") or 0) + (T.get("garage") or 0)
    lines = report.get("lines") or {}
    keys = ("income", "expenses", "profit", "investor_part", "gps", "garage", "payouts")
    return {
        "name": report.get("name", ""), "start": report.get("start", ""), "end": report.get("end", ""),
        "closed": bool(report.get("closed")), "period_index": report.get("period_index", 0),
        "periods": report.get("periods") or [],
        "cars": [{"code": x["code"], "label": car_info.get(x["code"], ""), "percent": x.get("percent", 0),
                  "note": ((notes or {}).get(x["code"]) or {}).get("text", ""),
                  **{k: x.get(k, 0) for k in keys}} for x in report.get("cars") or []],
        "total": {k: T.get(k, 0) for k in keys},
        "fixed": fixed,
        "to_pay": (T.get("investor_part") or 0) - fixed - (T.get("payouts") or 0),
        "expenses": [{"date": e.get("date", "")[:10], "car": e.get("car", ""), "amount": e.get("amount", 0),
                      "what": e.get("what") or e.get("text") or e.get("category") or "",
                      "category": e.get("category", ""), "share": e.get("share", "shared"),
                      "parts": [{k: p.get(k) for k in ("name", "brand", "position", "price", "labor")}
                                for p in e.get("parts") or []]}
                     for e in lines.get("expenses") or []],
        "payouts": [{"date": p.get("date", "")[:10], "amount": p.get("amount", 0)}
                    for p in lines.get("payouts") or [] if p.get("counted", True)],   # same as in the total
    }


def register(app, *, same_origin, public_url, writes_enabled, static_dir, current_owner, names, load_report):
    """load_report(investor, period_index) -> (report, notes, car_info), or None when he has no cars."""

    def raw_cookie():
        raw = request.cookies.get(COOKIE, "")
        return raw if raw and len(raw) <= 256 else ""

    def session_row():
        raw = raw_cookie()
        eng = _engine()
        if not raw or not _ready(eng):
            return None
        with eng.connect() as c:
            row = c.execute(select(access).where(access.c.token_hash == _hash(raw))).mappings().first()
        if not row or row["kind"] != "session" or row["revoked_at"] is not None or row["expires_at"] <= time.time() \
                or row["investor"] not in names:
            return None
        return row

    def gone():
        resp = jsonify(ok=False, message="Вход закрыт. Попросите у владельца парка новую ссылку.")
        resp.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return resp, 401

    def who():
        """(investor key, preview?) or (None, False)."""
        preview = request.args.get("investor")
        if preview is not None:
            if not current_owner():
                abort(401)
            if preview not in names:
                abort(404)
            return preview, True
        row = session_row()
        return (row["investor"], False) if row else (None, False)

    def period():
        try:
            return max(0, int(request.args.get("period", 0) or 0))
        except ValueError:
            return 0

    @app.get("/i")
    def investor_page():
        if request.query_string and set(request.args) - {"investor"}:
            abort(400)      # the link token travels only in the #fragment
        return send_file(static_dir / "investor.html", mimetype="text/html", max_age=0)

    @app.post("/i/login")
    def investor_login():
        if not same_origin():
            abort(403)
        if not writes_enabled:
            return jsonify(ok=False, message="Вход временно недоступен"), 503
        ticket = (request.get_json(silent=True) or {}).get("ticket")
        bad = (jsonify(ok=False, message="Ссылка недействительна или уже использована. "
                                         "Попросите новую у владельца парка."), 401)
        eng = _engine()
        if not isinstance(ticket, str) or not ticket or len(ticket) > 256 or not _ready(eng):
            return bad
        now = time.time()
        with eng.begin() as c:
            row = c.execute(select(access).where(access.c.token_hash == _hash(ticket))).mappings().first()
            if not row or row["kind"] != "link" or row["investor"] not in names:
                return bad
            used = c.execute(access.update().where(
                access.c.token_hash == row["token_hash"], access.c.consumed_at.is_(None),
                access.c.revoked_at.is_(None), access.c.expires_at > now).values(consumed_at=now))
            if used.rowcount != 1:
                return bad
            raw = secrets.token_urlsafe(32)
            c.execute(access.insert().values(token_hash=_hash(raw), kind="session", investor=row["investor"],
                                             csrf_token=secrets.token_urlsafe(32), created_at=now,
                                             expires_at=now + SESSION_TTL))
        resp = jsonify(ok=True)
        resp.set_cookie(COOKIE, raw, max_age=SESSION_TTL, path="/", secure=True, httponly=True, samesite="Lax")
        return resp

    @app.get("/api/i/me")
    def investor_me():
        key, preview = who()
        if not key:
            return gone()
        got = load_report(key, period())
        if got is None:
            return jsonify(ok=True, preview=preview, csrf="", name=names[key], cars=[], periods=[])
        report, notes, info = got
        row = None if preview else session_row()
        return jsonify(ok=True, preview=preview, csrf=row["csrf_token"] if row else "",
                       **public_report(report, notes, info))

    @app.get("/api/i/report.pdf")
    def investor_pdf():
        key, _ = who()
        if not key:
            return gone()
        got = load_report(key, period())
        if got is None:
            abort(404)
        report, notes, info = got
        from . import invpdf
        try:
            body = invpdf.build(report, notes, info)
        except RuntimeError as e:
            return jsonify(ok=False, message=str(e)), 500
        import io
        return send_file(io.BytesIO(body), mimetype="application/pdf", as_attachment=True,
                         download_name=f"Отчёт {report['name']} {report['start']} — {report['end']}.pdf")

    @app.post("/api/i/logout")
    def investor_logout():
        row = session_row()
        if row and same_origin() and hmac.compare_digest(row["csrf_token"] or "", request.headers.get("X-CSRF", "")):
            with _engine().begin() as c:
                c.execute(access.update().where(access.c.token_hash == row["token_hash"])
                          .values(revoked_at=time.time()))
        resp = jsonify(ok=True)
        resp.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
        return resp

    def link_url(raw):
        return public_url + "/i#token=" + quote(raw, safe="")

    return link_url
