from flask import Blueprint, jsonify, request
from .db import Session
from .utils import find_car
from .driver_voice import parse_driver_lookup, current_driver_response

bp_assistant_voice = Blueprint('assistant_voice', __name__)

@bp_assistant_voice.route('/api/assistant/voice/lookup', methods=['POST'])
def voice_lookup():
    data = request.get_json(silent=True) or {}
    command = parse_driver_lookup(data.get('text'))
    if not command:
        return jsonify(ok=False, error='Команда не распознана'), 422
    with Session() as db:
        result = current_driver_response(find_car(db, command['car_code']))
    return jsonify(result), 200 if result['ok'] else 404
