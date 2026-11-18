"""Investor report for one settlement period (16th -> 15th) with checks. Read-only.

The split follows the old FleetAI's calculate_period_for_car (income minus shared
expenses, times the investor's percent from the database; investor-only expenses
come off the investor's share), plus the owner's agreement from 14.11.2026:
GPS 500 ₽ per car and garage 3 000 ₽ per month split across all cars, unless such
an expense is already booked in the period. Rows are read once and processed in
Python: calculate_period_for_car does one query per expense, too slow for a
two-year history. tests/test_dashboard_invreport.py checks both give the same numbers.

"History" is a running balance from the first period with data: what the
investor earned minus what was paid. A negative balance means the investor was
paid more than earned. Checks only point at records to look at; nothing is changed.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from fleetai.finance import (INVESTOR_ONLY_TYPES, PARK_ONLY_TYPES, moscow_now,
                             period_bounds_for_car)
from fleetai.models import (Car, Downtime, Expense, Income, InvestorInvestment,
                            InvestorPayout, InvestorSettlement, Operation, Part)

from .data import RETIRED_CODES, owner_key

KOP = 100
GPS_PER_CAR_RUB = 500
GARAGE_PER_MONTH_RUB = 3000
AGREED = {"ilya": 75, "ravshan": 70, "mark": 75}     # owner, 14.11.2026
NAMES = {"ilya": "Илья", "ravshan": "Равшан", "mark": "Марк"}
RECURRING_RE = re.compile(r"gps|жпс|трекер|wialon|гараж", re.I)
DEPOSIT_RE = re.compile(r"залог|депозит", re.I)
LEAD_CODE_RE = re.compile(r"^\D{0,3}(\d{3})(?!\d)")
MAX_PERIODS = 24
BIG_EXPENSE_RUB = 15000


def _code(v):
    return str(v or "").strip()


def _shift(dt, months):
    m = dt.month - 1 + months
    return dt.replace(year=dt.year + m // 12, month=m % 12 + 1)


def _iso(d):
    return d.isoformat() if d else ""


def _expense_kind(row, op_types):
    if row.operation_id and op_types.get(row.operation_id) == "investor_expense_split":
        return "investor_only"
    v = (row.share_type or "shared").strip().lower()
    if v in INVESTOR_ONLY_TYPES:
        return "investor_only"
    if v in PARK_ONLY_TYPES:
        return "park_only"
    return "shared"


def periods_for(cars, now=None, count=12):
    """[(index, start, end)] - 0 is the current period, 1 the previous..."""
    now = now or moscow_now()
    start, _ = period_bounds_for_car(cars[0], now=now)
    return [(i, _shift(start, -i), _shift(start, -i + 1)) for i in range(count)]


class _Data:
    """Every row the report needs, read once."""

    def __init__(self, s, codes, investor_key):
        self.ops = {o.id: o for o in s.query(Operation).all()}
        op_types = {i: o.type for i, o in self.ops.items()}
        want = set(codes) | set(RETIRED_CODES)
        self.income = [r for r in s.query(Income).all() if _code(r.car_code) in want and r.date]
        self.expense = [r for r in s.query(Expense).all() if _code(r.car_code) in want and r.date]
        self.parts = defaultdict(list)
        for r in s.query(Part).all():
            if r.operation_id and _code(r.car_code) in want:
                self.parts[r.operation_id].append(r)
        for r in self.expense:
            r._kind = _expense_kind(r, op_types)
        self.payouts = [r for r in s.query(InvestorPayout).all() if r.date and (
            _code(r.car_code) in codes or owner_key("investor", r.investor_name) == investor_key)]
        self.invested = [r for r in s.query(InvestorInvestment).all() if r.date and _code(r.car_code) in codes]
        self.settle = [r for r in s.query(InvestorSettlement).all() if r.date and _code(r.car_code) in codes]
        self.downtime = [r for r in s.query(Downtime).all() if _code(r.car_code) in codes]

    def what(self, op_id):
        """Plain words for the investor: what the money was spent on."""
        o = self.ops.get(op_id) if op_id else None
        if not o:
            return ""
        desc = (o.description or "").strip()
        if not desc or desc.lower() in ("расход", "ремонт", "доход"):
            desc = re.sub(r"\[[A-Z_]+:[^\]]*\]", "", o.raw_message or "")
            desc = re.sub(r"^\s*\d{3}\.?\s*", "", desc).strip()
        return desc[:200]

    def part_list(self, op_id):
        return [{"name": (p.part_name or "").strip(), "brand": (p.brand or "").strip(), "position": (p.position or "").strip(),
                 "price": _k(p.price), "labor": _k(p.labor)} for p in self.parts.get(op_id, [])] if op_id else []

    def raw(self, op_id):
        o = self.ops.get(op_id) if op_id else None
        return ((o.raw_message or o.description or "") if o else "")[:200]


def _in(rows, code, a, b):
    return [r for r in rows if _code(r.car_code) == code and a <= r.date < b]


def _downtime_days(rows, code, a, b, now):
    total = 0
    for r in rows:
        if _code(r.car_code) != code:
            continue
        ds = r.start_date or a
        de = now if (r.active or not r.end_date) else r.end_date
        lo, hi = max(ds, a), min(de, b)
        if hi > lo:
            total += max((hi.date() - lo.date()).days, 1)
    return total


def _car_period(d, car, a, b, garage_rub):
    """Numbers for one car and one period, in rubles."""
    code = _code(car.code)
    inc = _in(d.income, code, a, b)
    exp = _in(d.expense, code, a, b)
    income = sum(r.amount or 0 for r in inc)
    shared = sum(r.amount or 0 for r in exp if r._kind == "shared")
    inv_only = sum(r.amount or 0 for r in exp if r._kind == "investor_only")
    park_only = sum(r.amount or 0 for r in exp if r._kind == "park_only")
    pct = int(car.investor_percent or 0) if car.owner_type == "investor" else 0
    profit = income - shared
    share = round(profit * pct / 100)
    settle_ids = {r.operation_id for r in _in(d.settle, code, a, b) if r.operation_id}
    paid_in = sum(r.investor_paid or 0 for r in _in(d.settle, code, a, b)) + sum(
        r.amount or 0 for r in _in(d.invested, code, a, b) if not (r.operation_id and r.operation_id in settle_ids))
    payouts = sum(r.amount or 0 for r in _in(d.payouts, code, a, b))
    booked = any(RECURRING_RE.search(r.category or "") for r in exp)
    active = bool(inc or exp) or any(_code(r.car_code) == code and r.date < b for r in d.income)
    fixed = 0 if (booked or not active or car.owner_type != "investor") else GPS_PER_CAR_RUB + garage_rub
    earned = share - inv_only + paid_in - fixed
    return {"code": code, "percent": pct, "db_percent": int(car.investor_percent or 0),
            "owner_type": car.owner_type or "own", "income": income, "shared_expenses": shared,
            "investor_only_expenses": inv_only, "park_only_expenses": park_only, "profit_for_split": profit,
            "share": share, "investor_paid": paid_in, "gps": 0 if fixed == 0 else GPS_PER_CAR_RUB,
            "garage": 0 if fixed == 0 else garage_rub, "recurring_booked": booked, "earned": earned,
            "payouts": payouts, "due": earned - payouts, "active": active,
            # simple view for the report: received, all expenses, profit, investor's part
            "expenses": shared + inv_only + park_only, "profit": income - shared - inv_only - park_only,
            "investor_part": share - inv_only}


def _k(v):
    return int(v or 0) * KOP


def _money_row(row):
    return {k: (_k(v) if isinstance(v, int) and not isinstance(v, bool) and k not in ("percent", "db_percent") else v)
            for k, v in row.items()}


def investor_report(engine, investor_key, period_index=0, now=None):
    now = now or moscow_now()
    if investor_key not in NAMES:
        raise ValueError("unknown investor")
    period_index = max(0, min(int(period_index or 0), MAX_PERIODS - 1))
    with Session(engine) as s:
        all_cars = [c for c in s.query(Car).order_by(Car.code).all() if _code(c.code) not in RETIRED_CODES]
        cars = [c for c in all_cars if owner_key(c.owner_type, c.investor_name) == investor_key]
        if not cars:
            return {"investor": investor_key, "name": NAMES[investor_key], "cars": [], "checks": [], "periods": []}
        n_all = len(all_cars) or 1
        garage_rub = round(GARAGE_PER_MONTH_RUB / n_all)
        codes = {_code(c.code) for c in cars}
        d = _Data(s, codes, investor_key)
        plist = periods_for(cars, now, MAX_PERIODS)
        _, a, b = plist[period_index]
        rows = [_car_period(d, c, a, b, garage_rub) for c in cars]
        daily = {_code(c.code): _daily(c) for c in cars}

        # --- history: running balance from the first period that has data ---
        first = min([r.date for r in d.income + d.expense + d.payouts if _code(r.car_code) in codes] or [a])
        hist, bal = [], 0
        for i, pa, pb in reversed(plist):
            if pb <= first or i < period_index:
                continue
            per = [_car_period(d, c, pa, pb, garage_rub) for c in cars]
            stray = sum(r.amount or 0 for r in d.payouts if _code(r.car_code) not in codes and pa <= r.date < pb)
            earned, paid = sum(x["earned"] for x in per), sum(x["payouts"] for x in per) + stray
            bal += earned - paid
            hist.append({"index": i, "start": _iso(pa.date()), "end": _iso((pb - timedelta(days=1)).date()),
                         "income": _k(sum(x["income"] for x in per)), "share": _k(sum(x["share"] for x in per)),
                         "investor_only_expenses": _k(sum(x["investor_only_expenses"] for x in per)),
                         "fixed": _k(sum(x["gps"] + x["garage"] for x in per)),
                         "earned": _k(earned), "paid": _k(paid), "balance": _k(bal)})
        balance_at_end = hist[-1]["balance"] if hist else 0

        lines = _lines(d, codes, a, b)
        checks = _checks(d, cars, rows, codes, a, b, now, daily, balance_at_end, investor_key, lines)

    total = {k: sum(r[k] for r in rows) for k in ("income", "shared_expenses", "investor_only_expenses",
                                                  "park_only_expenses", "profit_for_split", "share",
                                                  "investor_paid", "gps", "garage", "earned", "payouts", "due",
                                                  "expenses", "profit", "investor_part")}
    return {
        "investor": investor_key, "name": NAMES[investor_key], "agreed_percent": AGREED.get(investor_key),
        "period_index": period_index, "start": _iso(a.date()), "end": _iso((b - timedelta(days=1)).date()),
        "closed": b <= now, "generated_at": now.isoformat(timespec="minutes"),
        "periods": [{"index": i, "start": _iso(pa.date()), "end": _iso((pb - timedelta(days=1)).date())}
                    for i, pa, pb in plist[:12]],
        "cars": [_money_row(r) for r in rows], "total": _money_row(total),
        "history": list(reversed(hist)), "balance": balance_at_end,
        "lines": lines, "checks": checks,
    }


def car_codes(engine, investor_key):
    with Session(engine) as s:
        return {_code(c.code) for c in s.query(Car).all()
                if _code(c.code) not in RETIRED_CODES and owner_key(c.owner_type, c.investor_name) == investor_key}


def _daily(car):
    from fleetai.routes import effective_daily_rent
    return int(effective_daily_rent(car) or 0)


def _lines(d, codes, a, b):
    def inc(r):
        return {"id": r.id, "op": r.operation_id, "date": r.date.isoformat(timespec="minutes"), "car": _code(r.car_code),
                "amount": _k(r.amount), "kind": r.income_type or "", "text": d.raw(r.operation_id)}

    def exp(r):
        return {"id": r.id, "op": r.operation_id, "date": r.date.isoformat(timespec="minutes"), "car": _code(r.car_code),
                "amount": _k(r.amount), "category": r.category or "", "share": r._kind, "text": d.raw(r.operation_id),
                "what": d.what(r.operation_id), "parts": d.part_list(r.operation_id)}

    def pay(r):
        return {"id": r.id, "op": r.operation_id, "date": r.date.isoformat(timespec="minutes"), "car": _code(r.car_code),
                "amount": _k(r.amount), "investor": r.investor_name or "", "counted": _code(r.car_code) in codes,
                "text": (r.comment or "")[:200] or d.raw(r.operation_id)}

    def when(rows):
        return sorted((r for r in rows if a <= r.date < b), key=lambda r: (r.date, r.id))

    return {
        "income": [inc(r) for r in when(r for r in d.income if _code(r.car_code) in codes)],
        "expenses": [exp(r) for r in when(r for r in d.expense if _code(r.car_code) in codes)],
        "payouts": [pay(r) for r in when(d.payouts)],
        "investor_paid": [{"date": r.date.isoformat(timespec="minutes"), "car": _code(r.car_code), "amount": _k(r.amount),
                           "text": (r.comment or "")[:200] or d.raw(r.operation_id)} for r in when(d.invested)],
    }


def _check(level, title, detail, items=None, amount=0, ops=None):
    """ops[i] - operation ids behind items[i], so the page can offer edit/delete."""
    items = items or []
    ops = [[int(x) for x in (o or []) if x] for o in (ops or [])]
    return {"level": level, "title": title, "detail": detail, "items": items, "amount": amount,
            "ops": (ops + [[]] * len(items))[:len(items)]}


def _checks(d, cars, rows, codes, a, b, now, daily, balance, key, lines):
    out = []
    by = {r["code"]: r for r in rows}
    pct_of = {_code(c.code): (int(c.investor_percent or 0) if c.owner_type == "investor" else 0) for c in cars}

    # 1. paid more than earned (running balance)
    if balance < 0:
        out.append(_check("bad", "Выплачено больше, чем заработано",
                          "С первого периода с данными по конец этого периода инвестору выплачено больше его доли "
                          "(доля − расходы инвестора − GPS и гараж). Смотрите таблицу «История» ниже.", amount=-balance))
    paid_now = sum(r["payouts"] for r in rows)
    earned_now = sum(r["earned"] for r in rows)
    if paid_now > 0 and paid_now > max(earned_now, 0) and balance >= 0:
        out.append(_check("info", "В этом периоде выплачено больше, чем заработано за него",
                          "По общему итогу переплаты нет: выплата покрывает остаток прошлых периодов.",
                          amount=_k(paid_now - max(earned_now, 0))))

    # 2. percent / owner type
    for c in cars:
        code, agreed = _code(c.code), AGREED.get(key)
        r = by[code]
        if c.owner_type != "investor":
            out.append(_check("bad", f"{code}: в базе машина записана как своя",
                              "Доля инвестору по этой машине не начисляется. Нужно исправить тип в базе.",
                              amount=_k(round(r["profit_for_split"] * (agreed or 0) / 100))))
        elif agreed and int(c.investor_percent or 0) != agreed:
            diff = round(r["profit_for_split"] * (int(c.investor_percent or 0) - agreed) / 100)
            out.append(_check("bad" if diff > 0 else "warn",
                              f"{code}: в базе {int(c.investor_percent or 0)}%, по договорённости {agreed}%",
                              "Разница в доле за период: " + ("инвестору начислено больше." if diff > 0 else "инвестору начислено меньше."),
                              amount=_k(abs(diff))))

    # 3. duplicate payouts
    pays = sorted(d.payouts, key=lambda r: r.date)
    dup, dup_ops = [], []
    for i, p in enumerate(pays):
        for q in pays[i + 1:]:
            if q.date - p.date > timedelta(days=3):
                break
            if (q.amount or 0) == (p.amount or 0) and (a <= p.date < b or a <= q.date < b):
                dup.append(f"{p.date:%d.%m %H:%M} и {q.date:%d.%m %H:%M}: {p.amount:,} ₽ · машины {_code(p.car_code) or '—'} / {_code(q.car_code) or '—'}".replace(",", " "))
                dup_ops.append([p.operation_id, q.operation_id])
    if dup:
        out.append(_check("bad", "Похоже на двойную выплату",
                          "Одинаковая сумма выплаты в пределах 3 дней. Если это одна выплата — одну запись нужно удалить.",
                          dup, ops=dup_ops))

    # 4. payouts not counted on the investor's cars
    stray = [p for p in lines["payouts"] if not p["counted"]]
    if stray:
        out.append(_check("warn", "Выплаты инвестору записаны не на его машину",
                          "Эти выплаты не входят в расчёт по машинам инвестора — проверьте машину в записи. В «Истории» они учтены.",
                          [f"{p['date'][8:10]}.{p['date'][5:7]} · машина {p['car'] or '—'} · {p['amount'] // KOP:,} ₽ · {p['text']}".replace(",", " ") for p in stray],
                          amount=sum(p["amount"] for p in stray), ops=[[p["op"]] for p in stray]))
    foreign = [r for r in d.payouts if _code(r.car_code) in codes and a <= r.date < b and r.investor_name
               and owner_key("investor", r.investor_name) not in (key, "park")]
    if foreign:
        out.append(_check("warn", "Выплата на машину инвестора записана на другое имя",
                          "Сумма вычтена из доли этого инвестора, хотя в записи указан другой человек.",
                          [f"{r.date:%d.%m} · {_code(r.car_code)} · {r.investor_name} · {r.amount:,} ₽".replace(",", " ") for r in foreign],
                          amount=_k(sum(r.amount or 0 for r in foreign)), ops=[[r.operation_id] for r in foreign]))

    # 5. duplicate income (inflates the investor's share)
    inc = sorted((r for r in d.income if _code(r.car_code) in codes), key=lambda r: (_code(r.car_code), r.date))
    dup_inc, dup_inc_ops, extra = [], [], 0
    for i, p in enumerate(inc):
        for q in inc[i + 1:]:
            if _code(q.car_code) != _code(p.car_code) or q.date - p.date > timedelta(hours=24):
                break
            if (q.amount or 0) == (p.amount or 0) and (p.amount or 0) > 0 and a <= q.date < b:
                dup_inc.append(f"{_code(p.car_code)} · {p.date:%d.%m %H:%M} и {q.date:%d.%m %H:%M} · {p.amount:,} ₽ · операции #{p.operation_id or '—'} и #{q.operation_id or '—'}".replace(",", " "))
                dup_inc_ops.append([p.operation_id, q.operation_id])
                extra += round((q.amount or 0) * pct_of[_code(q.car_code)] / 100)
    if dup_inc:
        out.append(_check("warn", "Доход записан дважды?",
                          "Одинаковая сумма по одной машине в пределах суток. Если это одна оплата, доля инвестора завышена на сумму справа.",
                          dup_inc, amount=_k(extra), ops=dup_inc_ops))

    # 6. deposits counted as income
    dep = [x for x in lines["income"] if DEPOSIT_RE.search(x["text"] + " " + x["kind"])]
    if dep:
        out.append(_check("warn", "Залог водителя посчитан как доход",
                          "Залог возвращается водителю, но в расчёте он увеличивает долю инвестора.",
                          [f"{x['car']} · {x['date'][8:10]}.{x['date'][5:7]} · {x['amount'] // KOP:,} ₽ · {x['text']}".replace(",", " ") for x in dep],
                          amount=sum(round(x["amount"] * pct_of[x["car"]] / 100) for x in dep), ops=[[x["op"]] for x in dep]))

    # 7. income whose text names another car
    other, other_ops = [], []
    for x in lines["income"]:
        m = LEAD_CODE_RE.match(x["text"])
        if m and m.group(1) != x["car"] and RETIRED_CODES.get(m.group(1)) != x["car"]:
            other.append(f"{x['car']} · {x['date'][8:10]}.{x['date'][5:7]} · {x['amount'] // KOP:,} ₽ · «{x['text']}»".replace(",", " "))
            other_ops.append([x["op"]])
    if other:
        out.append(_check("warn", "В тексте операции другая машина",
                          "Доход записан на машину инвестора, а в команде указан другой номер.", other, ops=other_ops))

    # 8. more income than the car could earn in rent
    end = min(b, now)
    days = max((end.date() - a.date()).days + (1 if end < b else 0), 0)
    high = []
    for code in sorted(codes):
        r = by[code]
        rate = daily.get(code, 0)
        if not rate or not days:
            continue
        rent_income = r["income"] - sum(x["amount"] // KOP for x in dep if x["car"] == code)
        can = (days - _downtime_days(d.downtime, code, a, b, now)) * rate + 7 * rate     # + one week paid ahead
        if rent_income > can:
            high.append((code, rent_income, can, rent_income - can))
    if high:
        out.append(_check("warn", "Дохода больше, чем могла принести аренда",
                          f"За {days} дн. периода (без простоя) по ставке аренды плюс неделя вперёд. Проверьте лишние или ошибочные записи дохода.",
                          [f"{c}: доход {inc_:,} ₽, максимум ≈ {can:,} ₽".replace(",", " ") for c, inc_, can, _ in high],
                          amount=_k(sum(round(x[3] * pct_of[x[0]] / 100) for x in high))))

    # 9. income on the retired code 119 (not counted for 665)
    retired = [r for r in d.income + d.expense if _code(r.car_code) in RETIRED_CODES
               and RETIRED_CODES[_code(r.car_code)] in codes and a <= r.date < b]
    if retired:
        out.append(_check("info", "Записи на старый номер 119 не входят в расчёт",
                          "В базе осталась машина 119 (сейчас 665). Эти суммы не попали в долю инвестора.",
                          [f"{r.date:%d.%m} · {'доход' if isinstance(r, Income) else 'расход'} {r.amount:,} ₽ · {d.raw(r.operation_id)}".replace(",", " ") for r in retired],
                          ops=[[r.operation_id] for r in retired]))

    # 10. duplicate expenses
    exs = sorted((r for r in d.expense if _code(r.car_code) in codes and a <= r.date < b),
                 key=lambda r: (_code(r.car_code), r.date))
    dup_exp, dup_exp_ops = [], []
    for i, p in enumerate(exs):
        for q in exs[i + 1:]:
            if _code(q.car_code) != _code(p.car_code) or q.date - p.date > timedelta(hours=24):
                break
            if (q.amount or 0) == (p.amount or 0) and (p.amount or 0) > 0 and (q.category or "") == (p.category or ""):
                dup_exp.append(f"{_code(p.car_code)} · {p.date:%d.%m} · {p.category or '—'} · {p.amount:,} ₽ · операции #{p.operation_id or '—'} и #{q.operation_id or '—'}".replace(",", " "))
                dup_exp_ops.append([p.operation_id, q.operation_id])
    if dup_exp:
        out.append(_check("warn", "Расход записан дважды?",
                          "Одинаковый расход по одной машине в те же сутки. Лишний расход уменьшает долю инвестора.",
                          dup_exp, ops=dup_exp_ops))

    # 11. investor-only and large shared expenses - to look at
    io = [x for x in lines["expenses"] if x["share"] == "investor_only"]
    if io:
        out.append(_check("info", "Расходы только за счёт инвестора",
                          "Вычтены целиком из доли инвестора.",
                          [f"{x['car']} · {x['date'][8:10]}.{x['date'][5:7]} · {x['category']} · {x['amount'] // KOP:,} ₽".replace(",", " ") for x in io],
                          amount=sum(x["amount"] for x in io), ops=[[x["op"]] for x in io]))
    big = [x for x in lines["expenses"] if x["share"] == "shared" and x["amount"] >= BIG_EXPENSE_RUB * KOP]
    if big:
        out.append(_check("info", f"Крупные общие расходы (от {BIG_EXPENSE_RUB:,} ₽)".replace(",", " "),
                          "Делятся между инвестором и парком — стоит проверить, что они по этой машине.",
                          [f"{x['car']} · {x['date'][8:10]}.{x['date'][5:7]} · {x['category']} · {x['amount'] // KOP:,} ₽ · {x['text']}".replace(",", " ") for x in big],
                          ops=[[x["op"]] for x in big]))

    # 12. GPS / garage
    booked = [r["code"] for r in rows if r["recurring_booked"]]
    out.append(_check("info", "GPS и гараж",
                      f"Вычтено по договорённости: GPS {GPS_PER_CAR_RUB} ₽ за машину и доля гаража."
                      + (f" Уже внесены расходами в базе по машинам {', '.join(booked)} — там отдельно не вычитаются." if booked else ""),
                      amount=_k(sum(r["gps"] + r["garage"] for r in rows))))

    if not any(c["level"] in ("bad", "warn") for c in out):
        out.insert(0, _check("ok", "Лишних выплат не найдено",
                             "Переплаты, двойных выплат и записей на чужие машины нет."))
    order = {"bad": 0, "warn": 1, "ok": 2, "info": 3}
    return sorted(out, key=lambda c: order[c["level"]])
