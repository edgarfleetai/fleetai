# Hermes Finance API v1 — контракт чтения

Локальная реализация; не инструкция по развёртыванию. Экспорт: `fleetai.finance_readonly.bp`.
Регистрация blueprint, проверка credential и блокирование Hermes на старых маршрутах — обязанности общей policy/factory. Сам blueprint не импортирует старые обработчики, не проверяет пароль и не обновляет время использования credential.

## Доступ и методы

Префикс: `/api/integrations/hermes/v1`.

Только `g.principal.kind == "hermes"` и scope `finance:read`. Поддерживается principal-object с атрибутами либо словарь. Owner/driver отклоняются даже при наличии scope. Нет principal — `401`; недостаточно прав — `403`. Имена и credential не принимаются через query.

Четыре маршрута: `GET /debts`, `/balances`, `/rent-accruals`, `/payments`. Автоматические `HEAD` и `OPTIONS` проходят ту же проверку principal. Записывающие методы не зарегистрированы (`405` в blueprint; общая policy может отказать раньше).

## Общие параметры и ответ

- `car_code`: точное значение 1–32 символа: буквы/цифры/подчёркивание/дефис; без нормализации и пробелов.
- `from`, `to`: строго `YYYY-MM-DD`, включительно по календарным дням Москвы. `from <= to`; `to=9999-12-31` не поддерживается.
- `limit`: целое 1–100, по умолчанию 50.
- `after_id`: неотрицательный числовой первичный ключ выбранного реестра, по умолчанию 0; максимальное значение signed bigint.
- Только для `/payments`: `source=operations` (по умолчанию) либо `source=debt_payments`.
- Неизвестные/повторённые параметры и некорректные значения — `400`, JSON `error=invalid_query`.

Успех: `data` — массив, `currency="RUB"`, `timezone="Europe/Moscow"`, `as_of` — время чтения с offset; `pagination={limit,after_id,has_more,next_after_id}`. `next_after_id` — числовой PK последней выданной строки, только если есть следующая страница; иначе `null`. Порядок — PK ASC, извлекается не более `limit+1` строк результата. При переходе сохранять маршрут, источник и фильтры. PK-cursor защищает от сдвига offset, но не фиксирует snapshot между HTTP-запросами: параллельные изменения и backfill возможны.

Все денежные поля `*_amount_minor`/`amount_minor` — целые копейки (`Integer` рублей в старой модели ×100), знаки сохраняются. Даты без offset в старой базе интерпретируются как Europe/Moscow; историческая правильность этой предпосылки не доказана. `as_of` означает время извлечения, не свежесть расчётных обязательств и не cutoff исторического реестра.

## `/debts`

Источник: только сохранённый `DriverDebt`, не совокупная задолженность по аренде.

Поля: `id="debt:<PK>"`, `car_code`, `driver_name` из долгового реестра, `original_amount_minor`, `paid_amount_minor`, `remaining_amount_minor` из `balance`, `status`, `created_at`, `closed_at`, `source_confidence="unverified"`. Заголовок: `ledger="fixed_driver_debts"`, `includes_rental_obligations=false`.

Дата фильтра — `created_at`; суммы и статус текущие, не исторический snapshot на `to`. Ничего не пересчитывается и не закрывается. Не исправляются расхождения между original/paid/balance. Строки с видимыми тестовыми маркерами в reason/comment исключены.

## `/balances`

Одна строка на зарегистрированный `Car`, cursor по `Car.id`. Поля:

- `id="car:<PK>"`, `car_code`, `current_driver_name=Car.driver`.
- `account_scope="car_legacy_all_assignments"`, `driver_ownership_verified=false`: кошелёк привязан к автомобилю, надёжной эпохи смены водителя нет; сумма НЕ объявляется балансом нынешнего водителя.
- `wallet_balance_amount_minor`: SUM всех знаковых сохранённых wallet-транзакций автомобиля до конца `to`, либо всех сохранённых строк без `to`; `from` НЕ обнуляет начальный остаток.
- `wallet_period_net_amount_minor`: знаковое движение wallet внутри `from..to`.
- `fixed_debt_remaining_amount_minor`: отдельная SUM сохранённых `DriverDebt.balance` по точному car_code; не сумма по имени текущего водителя. `fixed_debt_temporality="current_not_historical"` даже с `to`.
- `ledgers_additive=false`: нет `total_due`, эти реестры не складываются и не вычитаются друг из друга.
- `last_posted_rent_date`: последняя сохранённая отрицательная `daily_rent` до `to` (не ограничена `from`), либо null.
- `stale=true`, если такой записи нет либо её дата раньше `min(сегодня в Москве,to)`. Это предупреждение о свежести, не доказательство долга; нулевая отметка пропуска/простоя не считается списанием.
- `source_confidence="unverified"`, `reconciliation_required=true`.

Метаданные: `ledger="car_wallet"`, `projected=false`, `wallet_cutoff_date`, `period_from`, `excludes_known_test_markers=true`, `completeness="persisted_unverified_ledger_only"`.

Wallet-only и старые `rent_payment` учитываются как есть со знаком. Начисления, архивирование, reconciliation и `driver_wallet_snapshot` НЕ вызываются. Осиротевшие кошельки без Car здесь не перечисляются; бескодовые фиксированные долги видны через `/debts`, но не приписываются произвольному автомобилю.

## `/rent-accruals`

Только сохранённые `DriverWalletTransaction` с `transaction_type="daily_rent"` и `amount<0`. Дата фильтра — `date`.

Поля: `id="wallet:<PK>"`, `car_code`, `recorded_driver_name`, `date`, отрицательный `amount_minor`, `posted=true`, `source`, `source_confidence="unverified"`.

Метаданные: `ledger="persisted_daily_rent"`, `zero_markers="excluded"`, `projected=false`. Нулевые отметки пропуска не выданы как начисления, положительные корректировки и прочие типы не включены. Пропущенные дни не достраиваются.

## `/payments`: два НЕ суммируемых источника

### `source=operations`

Канонический обычный feed — только `Operation.type="income"`, `category="Аренда"`, `amount>0`. Дата фильтра — `Operation.date`. Один PK → одна строка; `Income` и wallet не добавляются и не используются как подтверждение получения денег. Даже наличие нескольких `Income` с одним operation_id не размножает выдачу.

Поля: `id="operation:<PK>"`, `car_code`, `date`, `amount_minor`, `source_confidence="unverified"`, `bank_confirmed=null`, `reconciliation_required=true`.

`bank_confirmed=null` означает «API НЕ подтверждает банковское получение», а не «банк точно не получал платёж». Даже `[TBANK_PAYMENT:...]` сам по себе не повышает доверие. Сумма Operation может быть валовой, тогда как кошелёк после комиссии — нетто; по сумме/дате/водителю они НЕ объединяются.

### `source=debt_payments`

Отдельный `DriverDebtPayment.amount>0`, `id="debt_payment:<PK>"`, дополнительный `debt_id="debt:<PK>"`; остальные поля и оговорки такие же. Дата фильтра — `date`. Это позволяет читать платежи фиксированных долгов, которые путь `api_driver_debt_payment` пишет без Operation/Income.

Исключаются платежи с собственным тестовым комментарием, а также платежи, чей существующий родительский DriverDebt помечен в reason/comment как тестовый. Обычный комментарий платежа не отменяет маркировку долга. Платежи без существующего родительского долга сохраняются как unverified/reconciliation_required: отсутствие родителя не доказывает ни тестовое происхождение, ни банковское подтверждение.

Между долгами и Operation нет универсального надёжного linkage: объединённого `source=all` нет (`400`). `not_additive_with_operations=true` для debt-feed. Нельзя сложить два feed и назвать результат суммой всех поступлений: пересечения неизвестны.

Общие метаданные платежей: `feed`, `excluded_representations=[income,driver_wallet_transactions,driver_bank_payments]`, `completeness="selected_ledger_only"`, `cross_ledger_reconciliation="not_available"`. Возвраты/отрицательные корректировки не являются этим feed; orphan Income, wallet-only поступления и другие категории дохода НЕ представлены и не выдаются за полную банковскую выписку. Повторы между разными Operation PK не дедуплицируются предположениями.

## Происхождение, тестовые данные и границы

Видимые подстроки `test`, `simulator`, `simulation`, `demo`, русские `тест`/`эмулятор` (обычный, титульный и верхний регистры) исключаются в доступных source/marker/comment-полях: wallet.source/comment/external_id, Operation.raw_message/description, debt.reason/comment, debt_payment.comment. Это консервативная эвристика; возможны ложные исключения и немаркированные тестовые записи. SQLite LOWER не выполняет полный Unicode casefold. У старых тестовых сценариев зависимые списания могут иметь обычный source=system без linkage — их нельзя безопасно связать и удалить из чтения предположением. Поэтому всё оставшееся остаётся unverified; чистота production-реестра не обещана.

Соединение в развёрнутом приложении берётся из отдельного `FINANCE_READONLY_DATABASE_URL` (роль только SELECT). При отсутствии настройки новый API закрыт с `503`, без fallback на писательское подключение. Только в `TESTING` допускается явно изолированный `db.engine`. На PostgreSQL перед SELECT выполняется `SET TRANSACTION READ ONLY`; на SQLite — `PRAGMA query_only=ON`, явный BEGIN, rollback и восстановление прежнего query_only перед возвратом в pool. При ошибке восстановления соединение инвалидируется. Другие диалекты отклоняются. Ошибки datasource возвращаются без DSN/параметров/секретов. Только SELECT читает прикладные таблицы; ни auth last_used, ни rent sync, ни внешние транспорты blueprint не вызывает.

Интеграционные проверки HTTP и auth/policy/factory выполняются на изолированном SQLite в `.test-data`, включая запрет DML, восстановление pooled-state и полное сравнение SQL-dump всех таблиц до/после GET/HEAD/OPTIONS. Дополнительно точный PostgreSQL DDL схемы и триггеров отзыва исполняется в эфемерном PostgreSQL-WASM (PGlite), с проверкой ABA, rollback, DELETE и запрета записи в READ ONLY. Это не проверка нативного psycopg/сетевого пула: она остаётся обязательным шагом staging. Production, main, Render и реальные секреты не используются.
