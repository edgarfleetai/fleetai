"""Confirm a voice financial draft using the existing operations ledger."""
import json
import re
from sqlalchemy import select
from .models import Car, Operation, Income, Expense
from .voice_finance_receipt import VoiceFinanceReceipt


def commit_finance_draft(db, draft, *, approved, request_key):
    """Flush only. Caller commits or rolls back the entire transaction."""
    if approved is not True or not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
        raise ValueError('Нужно подтверждение и уникальный ключ операции')
    if not isinstance(draft, dict) or draft.get('kind') not in ('income', 'repair_expense'):
        raise ValueError('Неизвестный тип финансовой операции')
    code, amount, description = draft.get('car_code'), draft.get('amount_rub'), draft.get('description')
    if not isinstance(code, str) or not re.fullmatch(r'\d{3,4}', code):
        raise ValueError('Неверный номер машины')
    if type(amount) is not int or not 0 < amount <= 10000000:
        raise ValueError('Неверная сумма')
    if not isinstance(description, str) or not 0 < len(description.strip()) <= 500:
        raise ValueError('Нужно описание операции')
    prior = db.execute(select(VoiceFinanceReceipt).where(VoiceFinanceReceipt.request_key == request_key)).scalar_one_or_none()
    if prior:
        raise ValueError('Операция с этим ключом уже была обработана')
    car = db.execute(select(Car).where(Car.code == code).with_for_update()).scalar_one_or_none()
    if car is None:
        raise ValueError('Автомобиль не найден')
    kind = draft['kind']
    op = Operation(car_code=code, type='income' if kind == 'income' else 'repair',
                   category='Аренда' if kind == 'income' else 'Ремонт',
                   description=description.strip(), amount=amount, raw_message=description.strip())
    db.add(op)
    db.flush()
    if kind == 'income':
        db.add(Income(operation_id=op.id, car_code=code, amount=amount,
                      income_type=description.strip()))
    else:
        db.add(Expense(operation_id=op.id, car_code=code, category='Ремонт',
                       amount=amount, share_type='shared'))
    db.add(VoiceFinanceReceipt(request_key=request_key, car_code=code,
                               kind=kind, amount_rub=amount, operation_id=op.id,
                               raw_draft_json=json.dumps(draft, ensure_ascii=False)))
    db.flush()
    return {'ok': True, 'operation_id': op.id, 'car_code': code, 'amount_rub': amount,
            'kind': kind, 'request_key': request_key}
