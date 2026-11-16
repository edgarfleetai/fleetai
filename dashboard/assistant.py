"""AI assistant for the owner: answers questions about the fleet, sets tasks and
drafts operations. Runs on Claude through the Anthropic SDK.

Safety:
  * it reads only through the dashboard's own read functions (no free SQL);
    passports, phones and contracts are never given to it;
  * it can create tasks (additive table) and nothing else by itself;
  * money operations are only *proposed*: the owner presses "Сохранить" and the
    usual command line (preview -> commit) does the write;
  * no Wialon commands, ever.

A question runs in a background thread (a reply can take longer than the 30 s
gunicorn timeout); the page polls /api/v4/assistant/job/<id>.
"""
import json
import os
import secrets
import threading
import time
from datetime import datetime

from fleetai.finance import moscow_now

MODEL = os.environ.get("ASSISTANT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("ASSISTANT_EFFORT", "medium")
MAX_STEPS = 12                 # model calls per question
MAX_TOOL_CHARS = 40_000        # one tool result
MAX_TURNS = 40                 # messages kept in one conversation
DAILY_LIMIT = int(os.environ.get("ASSISTANT_DAILY_LIMIT", "150"))   # questions per day
CONV_TTL = 6 * 3600

SYSTEM = """Ты — помощник владельца таксопарка FleetAI (Казань, Набережные Челны, Елабуга, Нижнекамск).
Владелец сдаёт машины водителям в аренду, часть машин принадлежит инвесторам (они получают процент прибыли).
Ты видишь данные парка только через инструменты. Отвечай по-русски, коротко и по делу, простыми словами, без воды.

Как работать:
- Любые цифры (деньги, пробег, даты) бери только из инструментов. Не придумывай. Если данных нет — так и скажи.
- Машины называются трёхзначным кодом (404, 621, 665…). Код 119 — это старая запись машины, которая теперь ездит как 665.
- Деньги в рублях. Пробег в км. Масло меняют каждые 15 000 км; задача ставится за 1 000 км.
- «Что менялось» — смотри change_history (правки, удаления, изменения машин, в т.ч. сделанные через бота и старый сайт)
  и operations (ремонты, запчасти, расходы, доходы).
- Владелец иногда пишет в английской раскладке по ошибке (например «lfq ccskre» = «дай ссылку»). Понимай такие сообщения.

Что ты можешь делать сам:
- create_task — поставить задачу владельцу (появится в разделе «Задачи»). Ставь задачу, когда владелец просит
  или когда видишь конкретную проблему, которую надо решить (долг, масло, простой, нет связи с трекером).
  Перед созданием проверь tasks, чтобы не дублировать.

Чего ты сам НЕ делаешь:
- Не записываешь деньги и операции. Если владелец просит записать операцию («404 получил 13000»,
  «621 ремонт колодки 3000»), вызови propose_operation с командой в формате FleetAI. Владелец увидит кнопку
  «Сохранить» и сам подтвердит. Никогда не говори, что операция уже записана.
- Не управляешь машинами (блокировка двигателя и любые команды трекеру запрещены).
- Не даёшь юридических и налоговых гарантий; можешь давать деловые советы по парку, честно отмечая допущения.

Формат команд FleetAI: «<код> получил <сумма>», «<код> ремонт <что> <сумма>», «<код> масло <сумма> пробег <км>»,
«<код> запчасть <название> <сумма>», «<код> пробег <км>». Несколько частей можно разделять «/».
"""

TOOLS = [
    {"name": "fleet", "description": "Список машин: код, номер, модель, статус, водитель, владелец/инвестор и его процент, условия аренды, пробег из FleetAI.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "finance", "description": "Финансы по машинам за расчётный период: доход, расходы, прибыль, доля инвестора, к выплате инвестору, доля парка, дни простоя.",
     "input_schema": {"type": "object", "properties": {
         "period": {"type": "string", "enum": ["current", "previous"], "description": "current — текущий период, previous — прошлый"},
         "car": {"type": "string", "description": "код машины, если нужна одна"}}, "additionalProperties": False}},
    {"name": "rent", "description": "Аренда и долги водителей: суточная аренда, кошелёк водителя, сколько должен, просрочка, последние платежи.",
     "input_schema": {"type": "object", "properties": {"car": {"type": "string"}}, "additionalProperties": False}},
    {"name": "operations", "description": "Журнал операций (доходы, расходы, ремонты, запчасти, выплаты, пробег) за последние N дней, новые сверху.",
     "input_schema": {"type": "object", "properties": {
         "car": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 400},
         "contains": {"type": "string", "description": "фильтр по тексту, например «масло» или «колодки»"},
         "kind": {"type": "string", "enum": ["income", "expense", "repair", "parts", "investor", "other"]}},
         "additionalProperties": False}},
    {"name": "maintenance", "description": "Пробег за сегодня и месяц, одометр, когда меняли масло и сколько осталось до замены, история замен запчастей (как часто меняются).",
     "input_schema": {"type": "object", "properties": {"car": {"type": "string"}}, "additionalProperties": False}},
    {"name": "repairs", "description": "Установленные запчасти и расходы на ремонт за N дней.",
     "input_schema": {"type": "object", "properties": {"car": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 730}},
                      "additionalProperties": False}},
    {"name": "change_history", "description": "История изменений: что, когда и где поменяли (в дашборде, через бота или старый сайт): правки и удаления операций, смена водителя, номера, статуса, аренды.",
     "input_schema": {"type": "object", "properties": {"car": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 365}},
                      "additionalProperties": False}},
    {"name": "positions", "description": "Где сейчас машины по GPS (Wialon): едет или стоит, скорость, когда было последнее сообщение.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "tasks", "description": "Задачи владельца (открытые и выполненные).",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["open", "done", "all"]}},
                      "additionalProperties": False}},
    {"name": "create_task", "description": "Поставить задачу владельцу. Задача появится в разделе «Задачи».",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "что сделать, коротко"},
         "car_code": {"type": "string"}, "detail": {"type": "string"},
         "due_date": {"type": "string", "description": "срок ГГГГ-ММ-ДД, если есть"}},
         "required": ["title"], "additionalProperties": False}},
    {"name": "propose_operation", "description": "Подготовить запись операции в формате FleetAI. НЕ записывает: владелец увидит проверку и кнопку «Сохранить».",
     "input_schema": {"type": "object", "properties": {"message": {"type": "string", "description": "команда, например «404 получил 13000»"}},
                      "required": ["message"], "additionalProperties": False}},
]

STATUS_RU = {"active": "работает", "repair": "ремонт", "idle": "простой", "personal": "личная", "notready": "не готова",
             "nodata": "нет в базе"}


def rub(kop):
    return int(round((kop or 0) / 100))


class ToolError(Exception):
    pass


class Tools:
    """ctx: callables provided by the app (reads are cached there)."""

    def __init__(self, ctx, job):
        self.ctx, self.job = ctx, job

    def run(self, name, args):
        fn = getattr(self, "t_" + name, None)
        if not fn:
            raise ToolError("нет такого инструмента")
        return fn(**(args or {}))

    @staticmethod
    def _car(c):
        return str(c or "").strip()

    def t_fleet(self):
        cars = self.ctx["fleet"]()["cars"]
        return [{"code": c["code"], "plate": c["plate"], "model": c["model"], "year": c.get("year"),
                 "status": STATUS_RU.get(c["status"], c["status"]), "status_in_db": c.get("status_raw"),
                 "driver": c.get("driver_name") or "", "owner": c.get("owner"),
                 "investor": c.get("investor_name") or "", "investor_percent": c.get("investor_percent"),
                 "rent_terms": f'{c.get("terms")} {c.get("rate")}', "mileage_fleetai_km": c.get("mileage"),
                 "old_plates": c.get("plates"), "note": c.get("flag")} for c in cars]

    def t_finance(self, period="current", car=None):
        data = self.ctx["finance"]("previous" if period == "previous" else "current")
        rows = [r for r in data["cars"] if not car or r["code"] == self._car(car)]
        return {"period": period, "cars": [{
            "code": r["code"], "period": f'{r["period_start"]} — {r["period_end"]}',
            "owner_type": r["owner_type"], "investor": r["investor_name"], "investor_percent": r["investor_percent"],
            "income": rub(r["income"]), "expenses": rub(r["expenses"]), "profit": rub(r["profit"]),
            "investor_share_period": rub(r["period_share"]), "to_pay_investor_period": rub(r["period_due"]),
            "investor_only_expenses": rub(r["investor_only_expenses"]), "payouts_in_period": rub(r["payouts_in_period"]),
            "owner_amount": rub(r["owner_amount"]), "downtime_days": r["downtime_days"],
            "gps_fee": rub(r.get("gps")), "garage_share": rub(r.get("garage"))} for r in rows]}

    def t_rent(self, car=None):
        rows = [r for r in self.ctx["rent"]()["rentals"] if not car or r["code"] == self._car(car)]
        return [{"code": r["code"], "driver": r["driver"], "daily_rent": rub(r["daily_rent"]),
                 "weekly_payment": rub(r["weekly_payment"]), "deposit": rub(r["deposit"]),
                 "wallet_balance": rub(r["wallet"]), "amount_due": rub(r["amount_due"]),
                 "overdue": rub(r["overdue_total"]), "overdue_days": r["overdue_days"],
                 "next_payment": r["next_payment_date"], "debt_total": rub(r["debt_total"]),
                 "debts": [{"amount": rub(d["amount"]), "reason": d["reason"], "date": d["created_at"]} for d in r["debts"]],
                 "last_payments": [{"date": t["date"], "amount": rub(t["amount"]), "type": t["type"], "comment": t["comment"]}
                                   for t in r["transactions"][:6]]} for r in rows]

    KINDS = {"income": {"income"}, "expense": {"expense", "investor_expense_split"}, "repair": {"repair", "service"},
             "parts": {"part", "parts"}, "investor": {"investor_payout", "investor_investment"}}

    def t_operations(self, car=None, days=30, contains=None, kind=None):
        days = max(1, min(int(days or 30), 400))
        ops = self.ctx["journal"](days)["operations"]
        car, needle = self._car(car), (contains or "").strip().lower()
        out = []
        for o in ops:
            if car and o["car"] != car:
                continue
            if kind:
                known = set().union(*self.KINDS.values())
                if (kind == "other" and o["type"] in known) or (kind != "other" and o["type"] not in self.KINDS[kind]):
                    continue
            text = f'{o["category"]} {o["description"]} {o["raw"]}'.lower()
            if needle and needle not in text:
                continue
            out.append({"id": o["id"], "date": o["date"][:16], "car": o["car"], "type": o["label"],
                        "category": o["category"], "description": o["description"], "amount": rub(o["amount"]),
                        "command": o["raw"][:160]})
        totals = {}
        for o in out:
            totals[o["type"]] = totals.get(o["type"], 0) + o["amount"]
        return {"days": days, "count": len(out), "totals_by_type": totals, "operations": out[:200],
                "truncated": len(out) > 200}

    def t_maintenance(self, car=None):
        s = self.ctx["service"]()
        car = self._car(car)
        keep = lambda code: not car or code == car
        return {"oil_interval_km": s.get("oil_interval_km"), "error": s.get("error"),
                "cars": [{"code": c["code"], "odometer_km": c["odometer_km"], "odometer_source": c["source"],
                          "today_km": c["today_km"], "month_km": c["month_km"],
                          "month_incomplete": c["month_partial"], "oil": c["oil"]} for c in s["cars"] if keep(c["code"])],
                "part_replacements": [p for p in s["parts"] if keep(p["car"])],
                "auto_tasks": [t for t in s["tasks"] if keep(t["car"])]}

    def t_repairs(self, car=None, days=180):
        r = self.ctx["repairs"](max(1, min(int(days or 180), 730)))
        car = self._car(car)
        return {"parts": [dict(p, price=rub(p["price"]), labor=rub(p["labor"])) for p in r["parts"] if not car or p["car"] == car][:200],
                "expenses": [dict(e, amount=rub(e["amount"])) for e in r["expenses"] if not car or e["car"] == car][:200]}

    def t_change_history(self, car=None, days=30):
        return self.ctx["history"](self._car(car) or None, max(1, min(int(days or 30), 365)))

    def t_positions(self):
        units, error = self.ctx["positions"]()
        now = time.time()
        return {"error": error, "units": [{
            "car": u.get("car_code"), "name": u.get("name"),
            "moving": bool(u.get("speed_kmh")), "speed_kmh": u.get("speed_kmh"),
            "last_message_min_ago": int((now - u["time"]) / 60) if u.get("time") else None,
            "lat": round(u["lat"], 3) if u.get("lat") is not None else None,
            "lon": round(u["lon"], 3) if u.get("lon") is not None else None} for u in units]}

    def t_tasks(self, status="open"):
        return self.ctx["tasks"](None if status == "all" else (status or "open"))

    def t_create_task(self, title, car_code="", detail="", due_date=""):
        task_id, created = self.ctx["create_task"](
            {"title": title, "car_code": car_code, "detail": detail, "due_date": due_date})
        self.job["tasks"].append({"id": task_id, "title": title, "car": car_code, "created": created})
        return {"ok": True, "id": task_id, "message": "Задача создана" if created else "Такая открытая задача уже есть"}

    def t_propose_operation(self, message):
        message = str(message or "").strip()[:500]
        items = self.ctx["preview"](message)
        ok = bool(items) and not any(i.get("problem") for i in items)
        if ok:
            self.job["proposals"].append({"message": message,
                                          "items": [{"car": i["car"], "label": i["label"], "amount": rub(i["amount"]),
                                                     "description": i["description"]} for i in items]})
        return {"ok": ok, "saved": False,
                "parsed": [{"car": i["car"], "type": i["label"], "amount": rub(i["amount"]), "category": i["category"],
                            "description": i["description"], "problem": i.get("problem")} for i in items],
                "note": "Не записано. Владелец увидит кнопку «Сохранить»." if ok else "Команда не распознана — исправь формат."}


class Assistant:
    def __init__(self, ctx, client_factory=None, sync=False, logger=None):
        self.ctx, self.sync, self.logger = ctx, sync, logger
        self.client_factory = client_factory or self._default_client
        self.lock = threading.Lock()
        self.convs, self.jobs = {}, {}
        self.day, self.count = "", 0

    @staticmethod
    def _default_client():
        import anthropic
        return anthropic.Anthropic(timeout=180.0, max_retries=2)   # reads ANTHROPIC_API_KEY

    @staticmethod
    def configured():
        return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())

    def _gc(self):
        now = time.time()
        for store in (self.convs, self.jobs):
            for k in [k for k, v in store.items() if now - v["t"] > CONV_TTL]:
                store.pop(k, None)

    def ask(self, owner, message, conv_id=None):
        """Start a question. Returns (job_id, conv_id) or raises ValueError with a user message."""
        message = str(message or "").strip()[:4000]
        if not message:
            raise ValueError("Напишите вопрос")
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            self._gc()
            if self.day != today:
                self.day, self.count = today, 0
            if self.count >= DAILY_LIMIT:
                raise ValueError(f"На сегодня лимит вопросов исчерпан ({DAILY_LIMIT}). Завтра снова можно.")
            if any(j["owner"] == owner and j["status"] == "running" for j in self.jobs.values()):
                raise ValueError("Помощник ещё отвечает на прошлый вопрос")
            conv = self.convs.get(conv_id) if conv_id else None
            if not conv or conv["owner"] != owner or len(conv["messages"]) > MAX_TURNS:
                conv_id = secrets.token_urlsafe(12)
                conv = self.convs[conv_id] = {"owner": owner, "messages": [], "t": time.time()}
            self.count += 1
            job_id = secrets.token_urlsafe(12)
            job = self.jobs[job_id] = {"owner": owner, "status": "running", "reply": "", "tasks": [], "proposals": [],
                                       "tools": [], "error": "", "t": time.time(), "conv": conv_id}
        now = moscow_now()
        stamped = f"[Сейчас {now.strftime('%d.%m.%Y %H:%M')} МСК]\n{message}"
        if self.sync:
            self._run(conv, job, stamped)
        else:
            threading.Thread(target=self._run, args=(conv, job, stamped), name="fa4-assistant", daemon=True).start()
        return job_id, conv_id

    def job(self, owner, job_id):
        j = self.jobs.get(job_id)
        if not j or j["owner"] != owner:
            return None
        return {k: j[k] for k in ("status", "reply", "tasks", "proposals", "tools", "error", "conv")}

    def _run(self, conv, job, user_text):
        with conv.setdefault("lock", threading.Lock()):
            msgs = conv["messages"]
            start = len(msgs)
            msgs.append({"role": "user", "content": user_text})
            tools = Tools(self.ctx, job)
            try:
                client = self.client_factory()
                reply = ""
                for _ in range(MAX_STEPS):
                    resp = client.beta.messages.create(
                        model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=msgs,
                        output_config={"effort": EFFORT}, cache_control={"type": "ephemeral"},
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                    if self.logger and getattr(resp, "usage", None):
                        u = resp.usage
                        self.logger.info("assistant usage in=%s out=%s cache_read=%s", getattr(u, "input_tokens", None),
                                         getattr(u, "output_tokens", None), getattr(u, "cache_read_input_tokens", None))
                    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
                    if resp.stop_reason == "refusal":
                        del msgs[start:]
                        reply = "На этот вопрос я ответить не могу. Попробуйте сформулировать иначе."
                        break
                    msgs.append({"role": "assistant", "content": resp.content})
                    if resp.stop_reason == "pause_turn":
                        continue
                    calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
                    if resp.stop_reason != "tool_use" or not calls:
                        reply = text or ("Ответ получился слишком длинным, спросите точнее."
                                         if resp.stop_reason == "max_tokens" else "")
                        break
                    results = []
                    for call in calls:
                        job["tools"].append(call.name)
                        try:
                            out = json.dumps(tools.run(call.name, call.input if isinstance(call.input, dict) else {}),
                                             ensure_ascii=False, default=str)
                            if len(out) > MAX_TOOL_CHARS:
                                out = out[:MAX_TOOL_CHARS] + " …(обрезано: уточни фильтр — машину или период)"
                            results.append({"type": "tool_result", "tool_use_id": call.id, "content": out})
                        except (ToolError, ValueError, TypeError) as error:
                            results.append({"type": "tool_result", "tool_use_id": call.id,
                                            "content": f"Ошибка: {error}", "is_error": True})
                        except Exception as error:   # a data problem must not kill the answer
                            results.append({"type": "tool_result", "tool_use_id": call.id,
                                            "content": f"Ошибка данных: {type(error).__name__}", "is_error": True})
                    msgs.append({"role": "user", "content": results})
                else:
                    reply = reply or "Не успел закончить — вопрос слишком большой. Спросите по частям."
                    # leave no dangling tool calls in the conversation
                    if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
                        del msgs[start:]
                job.update(status="done", reply=reply or "Готово.")
            except Exception as error:
                del msgs[start:]
                job.update(status="error", error=_error_text(error))
                if self.logger:
                    self.logger.warning("assistant failed: %s", type(error).__name__)
            conv["t"] = time.time()


def _error_text(error):
    name = type(error).__name__
    if name == "AuthenticationError":
        return "Ключ ANTHROPIC_API_KEY не подходит — проверьте его в Render"
    if name == "PermissionDeniedError":
        return "У ключа нет доступа к модели"
    if name == "RateLimitError":
        return "Слишком много запросов или кончился лимит расходов в Anthropic. Подождите минуту."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Нет связи с Anthropic, попробуйте ещё раз"
    if name == "InternalServerError" or name == "OverloadedError":
        return "Сервис Anthropic перегружен, попробуйте через минуту"
    return f"Ошибка помощника: {name}"
