"""Owner-session-only, signed two-step wallet top-up API."""
import os
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from .db import Session
from .voice_wallet_preview import preview_wallet_topup
from .voice_wallet_commit import commit_wallet_topup
from .voice_finance_confirmation import sign_finance_preview, verify_finance_preview

bp_voice_wallet = Blueprint('voice_wallet', __name__)


@bp_voice_wallet.route('/api/assistant/wallet/preview', methods=['POST'])
def wallet_preview():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Неверный запрос'), 400
    with Session() as db:
        result = preview_wallet_topup(db, car_code=data.get('car_code'),
                                      amount_rub=data.get('amount_rub'),
                                      payment_method=data.get('payment_method', 'cash'))
    if not result['ok']:
        return jsonify(result), 422
    secret = os.getenv('FLEETAI_VOICE_CONFIRM_SECRET', '')
    if len(secret) < 32:
        return jsonify(ok=False, error='Секрет подтверждения не настроен'), 503
    result['confirmation_token'] = sign_finance_preview(secret, result)
    return jsonify(result), 200


@bp_voice_wallet.route('/api/assistant/wallet/confirm', methods=['POST'])
def wallet_confirm():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or data.get('approved') is not True:
        return jsonify(ok=False, error='Нужно подтверждение'), 400
    preview = verify_finance_preview(os.getenv('FLEETAI_VOICE_CONFIRM_SECRET', ''),
                                     data.get('confirmation_token'))
    if preview is None or preview.get('requires_confirmation') is not True:
        return jsonify(ok=False, error='Предпросмотр истёк'), 422
    try:
        with Session.begin() as db:
            result = commit_wallet_topup(db, preview, approved=True,
                                         request_key=data.get('request_key'))
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    except IntegrityError:
        return jsonify(ok=False, error='Операция уже была проведена'), 409
