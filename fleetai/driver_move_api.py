from flask import Blueprint, jsonify, request
from .db import Session
from .utils import find_car
from .driver_move_preview import preview_driver_move
from .driver_move_finance import review_driver_finances
from .driver_move_guard import assignment_fingerprint
from .driver_move_risk import financial_closeout_requirements
from .driver_move_closeout import build_closeout_plan
from .driver_move_voice import parse_driver_move_voice
from .driver_move_mobile import mobile_move_summary

bp_driver_move = Blueprint('driver_move_preview', __name__)

@bp_driver_move.route('/api/assistant/driver-move/preview', methods=['POST'])
def driver_move_preview():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Ожидается объект запроса'), 400
    command = None
    if 'text' in data:
        command = parse_driver_move_voice(data.get('text'))
        if not command:
            return jsonify(ok=False, error='Голосовая команда перестановки не распознана'), 422
    source = str(command['source'] if command else data.get('source', '')).strip()
    target = str(command['target'] if command else data.get('target', '')).strip()
    swap = command['swap'] if command else data.get('swap', False)
    if not source or not target:
        return jsonify(ok=False, error='Укажите две машины'), 400
    if type(swap) is not bool:
        return jsonify(ok=False, error='Некорректный признак обмена'), 400
    with Session() as db:
        cars = {code: find_car(db, code) for code in (source, target)}
        assignments = {code: car.driver for code, car in cars.items() if car is not None}
        result = preview_driver_move(assignments, source, target, swap=swap)
        if result['ok']:
            if command:
                result['recognized_command'] = command
            result['financial_review'] = review_driver_finances(db, [cars[source], cars[target]])
            result['assignment_fingerprint'] = assignment_fingerprint([cars[source], cars[target]])
            result['financial_closeout'] = financial_closeout_requirements(result['financial_review'])
            result['closeout_plan'] = build_closeout_plan(result['financial_review'], result['changes'])
            result['mobile_summary'] = mobile_move_summary(result)
    return jsonify(result), 200 if result['ok'] else 422
