"""Read-only MCP JSON-RPC tools for the isolated FleetAI staging database.

This transport is deliberately disabled unless a separate server-side bearer
credential is configured. OAuth integration is a separate prerequisite for
ChatGPT connection. Never expose a credential to the browser or repository.
"""
import os
import secrets
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from .db import Session
from .models import Car, Operation, Income, Expense

bp_mcp = Blueprint("fleetai_mcp", __name__)
TOOLS = [
    {"name": "fleet_cars", "description": "Read car codes, drivers and statuses", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "fleet_repairs", "description": "Read up to 100 latest repairs and services; optionally filter by car code", "inputSchema": {"type": "object", "properties": {"car_code": {"type": "string", "maxLength": 32}}, "additionalProperties": False}},
    {"name": "fleet_finance_summary", "description": "Read aggregated income and expenses for the fleet; amounts are raw ledger entries, not profit", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]

def _read(name, args):
    db = Session()
    try:
        if name == "fleet_cars":
            rows = db.query(Car).order_by(Car.code).limit(150).all()
            return [{"code": x.code, "brand": x.brand, "model": x.model, "driver": x.driver, "status": x.status} for x in rows]
        if name == "fleet_repairs":
            q = db.query(Operation).filter(Operation.type.in_(["repair", "service"]))
            code = args.get("car_code")
            if code:
                q = q.filter(Operation.car_code == code)
            rows = q.order_by(Operation.id.desc()).limit(100).all()
            return [{"id": x.id, "date": x.date.isoformat() if x.date else None, "car_code": x.car_code, "type": x.type, "description": x.description, "amount": x.amount} for x in rows]
        if name == "fleet_finance_summary":
            income = db.query(func.coalesce(func.sum(Income.amount), 0), func.count(Income.id)).one()
            expense = db.query(func.coalesce(func.sum(Expense.amount), 0), func.count(Expense.id)).one()
            return {"income_total": int(income[0]), "income_records": income[1], "expense_total": int(expense[0]), "expense_records": expense[1], "scope": "all_dates", "warning": "Raw sums; not investor or fleet net profit"}
        raise ValueError("Unknown tool")
    finally:
        db.close()

@bp_mcp.route("/mcp", methods=["POST"])
def mcp_post():
    if os.getenv("FLEETAI_STAGING_LOCKDOWN") != "1":
        return jsonify({"error": "mcp_disabled"}), 404
    token = os.getenv("FLEETAI_MCP_BEARER_TOKEN", "")
    auth = request.headers.get("Authorization", "")
    if len(token) < 32 or not auth.startswith("Bearer ") or not secrets.compare_digest(auth[7:], token):
        response = jsonify({"error": "unauthorized"})
        response.headers["WWW-Authenticate"] = 'Bearer realm="fleetai-staging"'
        response.headers["Cache-Control"] = "no-store"
        return response, 401
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"error": "origin_not_allowed"}), 403
    if request.content_length is None or request.content_length > 16384:
        return jsonify({"error": "invalid_request_size"}), 413
    if not request.is_json:
        return jsonify({"error": "unsupported_media_type"}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}), 400
    method, params, req_id = payload.get("method"), payload.get("params") or {}, payload.get("id")
    if not isinstance(params, dict):
        return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Invalid params"}})
    if method == "notifications/initialized":
        return "", 202
    if method == "ping":
        result = {}
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fleetai-staging", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in TOOLS} or not isinstance(args, dict) or set(args) - set(next(t["inputSchema"]["properties"] for t in TOOLS if t["name"] == name)) or (name == "fleet_repairs" and "car_code" in args and (not isinstance(args["car_code"], str) or len(args["car_code"]) > 32)):
            return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Invalid tool arguments"}})
        try:
            import json
            result = {"content": [{"type": "text", "text": json.dumps(_read(name, args), ensure_ascii=False, default=str)}], "isError": False}
        except Exception:
            result = {"content": [{"type": "text", "text": "Data temporarily unavailable"}], "isError": True}
    else:
        return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})
