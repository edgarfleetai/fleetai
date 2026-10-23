"""Admin-only financial voice operations, with explicit two-step confirmation."""
import os
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from .db import Session
from .utils import find_car
from .voice_finance_preview import preview_finance_voice
from .voice_finance_commit import commit_finance_draft
from .voice_finance_confirmation import sign_finance_preview, verify_finance_preview

bp_voice_finance = Blueprint('voice_finance', __name__)


@bp_voice_finance.route('/api/assistant/finance/preview', methods=['POST'])
def finance_preview():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('text'), str):
        return jsonify(ok=False, error='Требуется текст команды'), 400
    with Session() as db:
        result = preview_finance_voice(data['text'], lambda code: find_car(db, code))
    if result['ok']:
        secret = os.getenv('FLEETAI_VOICE_CONFIRM_SECRET', '')
        if len(secret) < 32:
            return jsonify(ok=False, error='Подтверждение голосовых операций не настроено'), 503
        result['confirmation_token'] = sign_finance_preview(secret, result['draft'])
    return jsonify(result), 200 if result['ok'] else 422


@bp_voice_finance.route('/api/assistant/finance/confirm', methods=['POST'])
def finance_confirm():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('approved') is not True:
        return jsonify(ok=False, error='Нужно явное подтверждение'), 400
    secret = os.getenv('FLEETAI_VOICE_CONFIRM_SECRET', '')
    signed_draft = verify_finance_preview(secret, data.get('confirmation_token'))
    if signed_draft is None:
        return jsonify(ok=False, error='Предпросмотр истёк или не подтверждён'), 422
    try:
        with Session.begin() as db:
            if find_car(db, signed_draft.get('car_code')) is None:
                return jsonify(ok=False, error='Автомобиль не найден'), 422
            result = commit_finance_draft(db, signed_draft, approved=True,
                                          request_key=data.get('request_key'))
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    except IntegrityError:
        return jsonify(ok=False, error='Операция уже была проведена'), 409
