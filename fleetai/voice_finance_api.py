"""Admin-only financial voice operations, with explicit two-step confirmation."""
from flask import Blueprint, jsonify, request
from .db import Session
from .utils import find_car
from .voice_finance_preview import preview_finance_voice
from .voice_finance_commit import commit_finance_draft

bp_voice_finance = Blueprint('voice_finance', __name__)


@bp_voice_finance.route('/api/assistant/finance/preview', methods=['POST'])
def finance_preview():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('text'), str):
        return jsonify(ok=False, error='Требуется текст команды'), 400
    with Session() as db:
        result = preview_finance_voice(data['text'], lambda code: find_car(db, code))
    return jsonify(result), 200 if result['ok'] else 422


@bp_voice_finance.route('/api/assistant/finance/confirm', methods=['POST'])
def finance_confirm():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('approved') is not True:
        return jsonify(ok=False, error='Нужно явное подтверждение'), 400
    text = data.get('text')
    if not isinstance(text, str):
        return jsonify(ok=False, error='Требуется исходный текст команды'), 400
    try:
        with Session.begin() as db:
            preview = preview_finance_voice(text, lambda code: find_car(db, code))
            if not preview['ok']:
                return jsonify(preview), 422
            result = commit_finance_draft(db, preview['draft'], approved=True,
                                          request_key=data.get('request_key'))
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
