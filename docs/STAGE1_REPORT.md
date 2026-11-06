# FleetAI — первый этап защиты финансового API

## Рабочее состояние

- Только локальная ветка `security/hermes-finance-readonly-20261106`.
- База исходного кода: `053144753b64e2b30c8cbeb2d102aed76b692da8`.
- Удалённые main и security-ветка при проверке остаются на этом SHA; push и развёртывание не выполнялись.
- Production-коммит и реальные задания Render не подтверждены: доступа к Render нет. SHA main не считается SHA production.

## Реализовано

### Владелец

Первичная регистрация через локальную административную CLI, скрытый ввод пароля и подтверждение, без публичного bootstrap и пароля по умолчанию. Пароль — scrypt (тесты используют явно ослабленный тестовый KDF только при TESTING). Singleton владельца обеспечивается фиксированным ID и ограничением БД; гонка bootstrap отклоняется. Серверная непрозрачная сессия хранит хеш случайного токена, срок не более 8 часов. Cookie Secure/HttpOnly/SameSite=Lax/Path=/, без Domain. Есть logout, CSRF и ограничение попыток входа.

### Водитель

Одноразовый вход до 5 минут выдаётся только уже привязанному приватному Telegram-чату. URL использует fragment, GET не расходует билет, подтверждение POST атомарно использует его один раз. Проверяется срок после блокировки назначения. Сессия ограничена текущим автомобилем, владельческие команды запрещены. Смена назначения отзывает сессии, билеты и Telegram-привязку, включая ABA и явное переназначение одинакового имени. Триггеры защищают также SQL-изменение/удаление назначения. Для нового входа после переназначения требуется новая привязка.

### Hermes

Отдельный хешируемый, отзываемый credential `finance:read`. Доступ только к четырём новым маршрутам `/api/integrations/hermes/v1/{debts,balances,rent-accruals,payments}`. Нет доступа к старым GET с записями, командам оплаты/назначения или браузерным сессиям. Неверный bearer не откатывается на cookie.

Вне TESTING новый API требует отдельный `FINANCE_READONLY_DATABASE_URL`, подготовленный с SELECT-only правами; без него ответ 503, без fallback на writer. Соединение обёрнуто в READ ONLY, для SQLite используется query_only с восстановлением pool-state. Ошибки не раскрывают DSN/SQL-параметры.

### Совместимость

Существующая логика начисления аренды, расчёта задолженности, создания банковского платежа и применения банковского платежа не удалена и проверена AST-сравнением с исходным коммитом. Начисления из legacy GET не выносились. Старый UI получает CSRF-заголовок через same-origin fetch shim. Неизвестные API GET защищены CSRF по умолчанию; есть узкий список чистых чтений/скачиваний. Лицензия PDF выдаётся авторизованной навигацией без CSRF, потому что ленивый DDL удалён из её чтения и перенесён в стартовую схему.

Банковский webhook сохраняет свою проверку подписи, подтверждённого статуса и повторов; сырые уведомления больше не печатаются в лог. Telegram webhook требует собственный секрет, cron — служебный секрет, а не браузерную сессию. Методы и query-secret старых cron сохранены до проверки реальных заданий. Договорные capability-маршруты не требуют входа владельца и сохраняют исходные проверки. Симулятор и тестовые пополнения не являются публичными production-функциями.

## Финансовые ограничения контракта

- Фиксированные долги, автомобильный кошелёк, проведённые начисления и оплаты не складываются как независимые поступления.
- Operation/Income/wallet не размножают одну оплату; feed платежей фиксированных долгов выдаётся отдельно, не суммируется автоматически.
- Неизвестное банковское подтверждение передаётся как `bank_confirmed=null`, не false/true.
- Сохранённые legacy-записи остаются unverified: полная сверка происхождения и тестовых данных не выполнена. Фильтрация видимых тестовых маркеров эвристическая. Кошелёк — счёт автомобиля по legacy-истории, не доказанная собственность текущего водителя.

## Исправления независимой проверки

Первый независимый review не был пройден. Воспроизведены и закрыты его блокирующие замечания:

- CSRF пропуск GET wialon block-preview; дополнительно введена защита новых API GET по умолчанию.
- Не-ASCII заголовок служебного секрета вызывал исключение — теперь контролируемый отказ.
- HTTPS Origin за TLS proxy — сравнение с явным каноническим HTTPS-origin без доверия произвольным forwarded headers.
- Гонка первичной регистрации — singleton на уровне БД и обработка конфликта.
- Неизвестность подтверждения оплаты — null вместо false.
- Порядок upgrade — создание таблиц, строгие идемпотентные legacy migrations, затем триггеры; на PostgreSQL одна транзакция и advisory lock.
- Обычная ссылка на PDF — чистое чтение и сохранение авторизации без заголовочного CSRF.

Дополнительно усилены defaults: явный staging-origin без production fallback, повторная проверка срока билета после row lock, изоляция пути БД в самой factory, отсутствие legacy seeding в тестах, Origin/Fetch Metadata proof для preauth POST.

Итоговый независимый review: **ПРОЙДЕН**, `passed=true`, блокирующих security/logic замечаний нет. Полный отчёт сохранён в `docs/INDEPENDENT_REVIEW_FINAL.json`. Проверено совпадение всех 27 хэшей проверенных source/test/dependency-файлов с фактическим кодом полного прогона. Квитанция — `docs/STAGE1_TEST_RECEIPT.json`, JUnit — `.test-data/stage1-final.xml`.

Reviewer отдельно установил `staging_ready=false`: локальное одобрение кода не подтверждает внешний PostgreSQL/pool/роль, HTTPS ingress и sandbox конфигурацию. Evidence gate закрыт фактическим совпадением тестов и хэшей; остальные эксплуатационные gates ниже остаются открыты.

## Реальные автоматические проверки

Команда:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-security/bin/python -B -m pytest -p no:cacheprovider --basetemp=.test-data/stage1-final tests -q --junitxml=.test-data/stage1-final.xml
```

Результат: **117 passed, 0 failed, 0 errors, 0 skipped**, 26.36 секунды. 18 предупреждений — существующие deprecation ReportLab и SQLite datetime adapter в Python 3.12; не ошибки тестов.

Проверены: анонимный запрет, роли/CSRF, owner bootstrap/session/logout/rate limit, driver одноразовость и конкурентное погашение, отзыв/ABA/rollback, ограничение машиной, Hermes scope/revocation/no-cookie-fallback, новая API пагинация/валидация/суммы/даты, отсутствие изменений всех таблиц при GET/HEAD/OPTIONS, SQLite запрет записи и pool restoration, отдельный datasource, реальные старые банковские обработчики с синтетическими подписями и повторами, Telegram и служебные границы, договорные 404, Node fetch shim, обновление старой схемы и PDF-навигация.

Точный PostgreSQL DDL и триггеры исполнены в эфемерном PostgreSQL-WASM (PGlite), с проверками ABA/rollback/delete и отказом DML в READ ONLY. Это не нативный тест psycopg или сетевого пула Render.

Изоляция: SQLite только `.test-data`, внешние сокеты/requests заблокированы, сервисные credentials удаляются из тестового процесса. Node harness получает только базовое окружение и синтетический SQL. Основной fleet.db не создан. AST 24 Python-файлов и git diff --check прошли; статический scan новых модулей не выявил literal credentials/eval/exec/shell invocation. Это ограниченный scan, не замена review.

## Готовность и следующий шаг

Локальный этап реализации и автоматической проверки завершён. Внешнее тестовое развёртывание **пока не одобрено**: независимый reviewer одобрил локальный код, но оставил эксплуатационные staging gates. Артефакт готов к следующему этапу подготовки изолированного стенда; ни staging, ни production автоматически не разворачиваются.

Для staging отдельно требуются:
1. Собственная пустая/синтетическая PostgreSQL и подтверждение нативного psycopg/pool/миграций.
2. Явный HTTPS public origin staging, проверка cookie/Origin за фактическим proxy.
3. Отдельная SELECT-only роль и FINANCE_READONLY_DATABASE_URL.
4. Локальная bootstrap владельца; реальный пароль и Hermes credential не через чат/Git.
5. Согласованный тестовый Telegram webhook-secret и банковский контур, без копирования production-секретов и без переключения production webhook.
6. До production — подтверждение production SHA, фактических cron и пополненного-флота начислений, реальных браузерных/договорных сценариев и отдельное согласие на migration/merge/deploy.

## Изменённые и добавленные файлы

Прикладной код:
- fleetai/__init__.py
- fleetai/auth.py
- fleetai/auth_models.py
- fleetai/db.py
- fleetai/finance_readonly.py
- fleetai/routes.py
- fleetai/security_policy.py

Тесты:
- tests/conftest.py
- tests/test_auth_core.py
- tests/test_browser_client.py
- tests/test_finance_readonly.py
- tests/test_legacy_boundaries.py
- tests/test_postgres_wasm.py
- tests/test_review_regressions.py
- tests/test_security_defaults.py
- tests/test_security_edge_cases.py
- tests/test_security_integration.py

Окружение разработчика:
- .gitignore
- package.json
- package-lock.json
- requirements-dev.txt

Документы и доказательства:
- docs/AUTH_BOOTSTRAP_AND_TESTING.md
- docs/HERMES_FINANCE_API.md
- docs/LEGACY_BOUNDARY_TESTS.md
- docs/SECURITY_STAGE1.md
- docs/STAGE1_REPORT.md
- docs/INDEPENDENT_REVIEW_FINAL.json
- docs/STAGE1_TEST_RECEIPT.json

Ничего не развёрнуто; production, main и Render не изменялись.
