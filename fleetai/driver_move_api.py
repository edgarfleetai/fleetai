from flask import Blueprint, jsonify, request
from .db import Session
from .utils import find_car
from .driver_move_preview import preview_driver_move

bp_driver_move = Blueprint('driver_move_preview', __name__)

@bp_driver_move.route('/api/assistant/driver-move/preview', methods=['POST'])
def driver_move_preview():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Ожидается объект запроса'), 400
    source = str(data.get('source', '')).strip()
    target = str(data.get('target', '')).strip()
    if not source or not target:
        return jsonify(ok=False, error='Укажите две машины'), 400
    if type(data.get('swap', False)) is not bool:
        return jsonify(ok=False, error='Некорректный признак обмена'), 400
    with Session() as db:
        cars = {code: find_car(db, code) for code in (source, target)}
        assignments = {code: car.driver for code, car in cars.items() if car is not None}
    result = preview_driver_move(assignments, source, target, swap=data.get('swap', False))
    return jsonify(result), 200 if result['ok'] else 422
