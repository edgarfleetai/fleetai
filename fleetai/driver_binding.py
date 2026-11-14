"""Atomic legacy Telegram enrollment, sharing assignment-revocation locks.

Pure database service: never sends messages or commits the caller transaction.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select, text
from .models import Car
from . import auth

MOSCOW = ZoneInfo('Europe/Moscow')


def _deadline(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(MOSCOW).replace(tzinfo=None) if value.tzinfo else value


def redeem_binding_link(session, raw_token, chat_id, username='', first_name=''):
    """Return (persisted car, None) or (None, safe message); caller commits.

    Lock before revalidating eligibility; claim unused/unexpired link by CAS.
    All app binding redemptions serialize on an advisory lock on PostgreSQL
    (also protecting the legacy manually allocated binding PK), then on sorted
    car rows shared with explicit assignment/revocation. SQLite tests reserve
    the writer transaction via the same car-lock helper.
    """
    chat_id = str(chat_id).strip()
    if not chat_id.isdigit() or int(chat_id) <= 0:
        return None, 'Вход доступен только в личном Telegram-чате.'
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 256:
        return None, 'Ссылка привязки недействительна. Попросите новую ссылку.'
    preliminary = session.execute(text(
        'SELECT car_code FROM driver_telegram_links WHERE link_token=:token LIMIT 1'),
        {'token':raw_token}).first()
    if not preliminary:
        return None, 'Ссылка привязки недействительна. Попросите новую ссылку.'
    code = preliminary.car_code
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(text('SELECT pg_advisory_xact_lock(684593121)'))
    previous = session.execute(text(
        'SELECT car_code FROM driver_telegram_bindings WHERE telegram_chat_id=:chat'),
        {'chat':chat_id}).scalars().all()
    affected = set(previous) | {code}
    for old_code in sorted(affected):
        auth.lock_driver_assignment(session, old_code)
    # SQLite may have waited for its first write reservation: refresh chat scope.
    refreshed = set(session.execute(text(
        'SELECT car_code FROM driver_telegram_bindings WHERE telegram_chat_id=:chat'),
        {'chat':chat_id}).scalars().all())
    for old_code in sorted(refreshed - affected):
        auth.lock_driver_assignment(session, old_code)
    affected |= refreshed
    link = session.execute(text(
        'SELECT id,car_code,driver_name,expires_at,used_at FROM driver_telegram_links '
        'WHERE link_token=:token LIMIT 1'), {'token':raw_token}).mappings().first()
    now = datetime.now(MOSCOW).replace(tzinfo=None)
    if not link or link['used_at'] is not None:
        return None, 'Ссылка уже использована или отозвана. Попросите новую ссылку.'
    deadline = _deadline(link['expires_at'])
    if deadline is None or deadline <= now:
        return None, 'Срок действия ссылки истёк. Попросите новую ссылку.'
    if link['car_code'] != code:
        return None, 'Назначение изменилось. Попросите новую ссылку.'
    car = session.execute(select(Car).where(Car.code == code)
                          .execution_options(populate_existing=True)).scalar_one_or_none()
    if not car or not (car.driver or '').strip() or (car.driver or '').strip() != (link['driver_name'] or '').strip():
        return None, 'Водитель изменился. Попросите новую ссылку.'
    claimed = session.execute(text(
        'UPDATE driver_telegram_links SET used_at=:now WHERE id=:id '
        'AND link_token=:token AND used_at IS NULL AND expires_at>:now'),
        {'now':now,'id':link['id'],'token':raw_token})
    if claimed.rowcount != 1:
        return None, 'Ссылка уже использована или отозвана. Попросите новую ссылку.'
    for old_code in sorted(affected):
        auth.revoke_driver_access(session, old_code,
            keep_link_id=link['id'] if old_code == code else None)
    next_id = int(session.execute(text('SELECT COALESCE(MAX(id),0)+1 FROM driver_telegram_bindings')).scalar())
    session.execute(text(
        'INSERT INTO driver_telegram_bindings '
        '(id,car_code,driver_name,telegram_chat_id,telegram_username,telegram_first_name,linked_at,last_alert_level) '
        "VALUES (:id,:code,:driver,:chat,:username,:first_name,:now,'')"),
        {'id':next_id,'code':code,'driver':car.driver.strip(),'chat':chat_id,
         'username':str(username)[:128],'first_name':str(first_name)[:256],'now':now})
    return car, None
