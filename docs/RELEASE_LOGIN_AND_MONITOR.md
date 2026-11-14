# Выпуск в production: вход владельца + мониторинг машин

PR #26, ветка `feature/wialon-positions-auth` (security-ветка + `/api/wialon/positions` + `/monitor`).
Выпуск = слияние PR в `main`, после чего Render разворачивает production.
**Не сливать без явного подтверждения владельца.**

## Что изменится для пользователей

| Было | Станет |
|---|---|
| Любой, кто знает адрес, видит и меняет всё | Вход по паролю владельца (`/auth/login`), сессия 8 часов |
| Удаление машины, операции, банк — без входа | Только после входа + защита от поддельных запросов (CSRF) |
| Блокировка двигателя 665 доступна всем по тексту в запросе | Блокировка отключена в коде (403, команда не уходит). Разблокировка — только владельцу |
| Нет карты машин | `/monitor` — живые позиции из Wialon, только для владельца |
| Cron и Telegram-webhook пропускаются, если секрет не задан | Без секрета — отказ (fail closed) |

## Что изменится в базе при первом запуске

Всё выполняется автоматически в одной транзакции под advisory-lock; существующие строки не меняются и не удаляются.

1. Новые таблицы: `auth_owners`, `auth_sessions`, `auth_login_attempts`, `auth_driver_tickets`, `auth_driver_epochs`, `auth_hermes_credentials` (`CREATE TABLE IF NOT EXISTS`).
2. Уникальный индекс `auth_car_code_trim_unique ON cars (trim(code))`.
3. Функция `fleetai_auth_revoke_driver()` и триггер `auth_driver_assignment` на `cars` (смена водителя отзывает его входы и Telegram-привязку этой машины).
4. Старые `ALTER TABLE … ADD COLUMN` теперь пропускаются, если колонка есть, а **любая другая ошибка останавливает запуск** (раньше ошибки глушились). Поэтому выпуск сначала проверяется на копии базы.

Предварительная проверка (только чтение):
```sql
SELECT trim(code), count(*) FROM cars GROUP BY trim(code) HAVING count(*) > 1;  -- должно быть 0 строк
```

## Настройки Render (сервис production)

| Переменная | Нужна? | Что будет без неё |
|---|---|---|
| `FLEETAI_PUBLIC_BASE_URL=https://fleetai-1.onrender.com` | **Новая, обязательна** | Вход всегда отклоняется — вы не попадёте в FleetAI |
| `CRON_SECRET` | Была, теперь обязательна | Cron-задачи (начисление аренды, уведомления) получают 403. Render Cron должен передавать её (`X-Admin-Secret` или `?secret=`) |
| `TELEGRAM_WEBHOOK_SECRET` | Была, теперь обязательна | Бот перестаёт принимать сообщения (503). Webhook должен быть зарегистрирован с этим `secret_token` |
| `WIALON_TOKEN` | Уже есть | Карта `/monitor` покажет ошибку |
| `WIALON_665_UNIT_ID=50613` | Рекомендуется | Страница 665 остаётся с ошибкой Wialon 7 |
| `FINANCE_READONLY_DATABASE_URL` | Не нужна сейчас | Только для Hermes API — он ответит 503 |

Не задавать в production: `TESTING`, `FLASK_DEBUG`, `ENABLE_TEST_PAYMENT_ROUTES`.

## Шаги выпуска

1. **Резервная копия** production-базы (`scripts/backup_database.sh`), проверить `pg_restore --list` и `.sha256`. Без копии дальше не идти.
2. **Проверка на копии**: развернуть ветку на отдельном сервисе Render с базой, восстановленной из копии шага 1 (не production `DATABASE_URL`). Убедиться, что сервис стартует, вход работает, `/monitor` показывает машины. Это проверяет миграции на реальной схеме.
3. **SQL-проверка дублей** кодов на production (выше).
4. **Переменные Render** production — по таблице.
5. **CI зелёный** в PR #26.
6. **Слияние PR в `main`** — только по команде владельца. Render развернёт новую версию.
7. **Пароль владельца** — в Render Shell production-сервиса:
   ```sh
   flask --app app auth bootstrap-owner --username <имя>
   ```
   До этого шага войти нельзя никому — сделать сразу после деплоя.
8. **Проверка после выпуска**:
   - `/api/cars` без входа → 401;
   - `/auth/login` → вход → главная открывается, данные на месте;
   - `/monitor` → машины с трекером на карте;
   - бот Telegram отвечает;
   - на следующий день: cron начислил аренду (операции появились).

## Откат

| Ситуация | Действие |
|---|---|
| Приложение не стартует / вход сломан | Render → Deploys → Rollback на предыдущий деплой. Новые таблицы, индекс и триггер старому коду не мешают |
| Мешают индекс или триггер | `DROP TRIGGER IF EXISTS auth_driver_assignment ON cars; DROP FUNCTION IF EXISTS fleetai_auth_revoke_driver(); DROP INDEX IF EXISTS auth_car_code_trim_unique;` |
| Бот не отвечает | Проверить `TELEGRAM_WEBHOOK_SECRET`, перерегистрировать webhook |
| Cron не прошёл | Проверить `CRON_SECRET` в сервисе и в Render Cron |
| Повреждены данные | Восстановить из копии шага 1 (`scripts/restore_database.sh`) — только по решению владельца |

Revert-коммит в `main` — альтернатива откату в Render, если нужно сохранить историю.
