# Выпуск в production: вход владельца + мониторинг машин

Ветка: `feature/wialon-positions-auth` (security-ветка + `/api/wialon/positions` + `/monitor`).
Выпуск = слияние PR в `main`, после чего Render разворачивает production.
**Не сливать без явного подтверждения владельца.**

## Что изменится для пользователей

| Было | Станет |
|---|---|
| Любой, кто знает адрес, видит и меняет всё | Вход по паролю владельца (`/auth/login`), сессия 8 часов |
| Удаление машины, операции, банк — без входа | Только после входа + защита от поддельных запросов (CSRF) |
| Блокировка двигателя 665 по тексту в запросе | Отклоняется (как в staging) |
| Нет карты машин | `/monitor` — живые позиции из Wialon, только для владельца |
| Cron и Telegram без проверки | Требуют секрет (см. настройки ниже) |

## Что изменится в базе (только добавления)

При старте приложение само выполнит:
1. Новые таблицы входа: `auth_owners`, `auth_sessions`, `auth_login_attempts`, `auth_driver_tickets`, `auth_driver_epochs`, `auth_hermes_credentials`, а также таблицы привязки Telegram водителей (`CREATE TABLE IF NOT EXISTS`).
2. Уникальный индекс `auth_car_code_trim_unique ON cars (trim(code))`.
   **Если в `cars` есть коды, отличающиеся только пробелами, приложение не стартует.** Проверка до выпуска (только чтение):
   ```sql
   SELECT trim(code), count(*) FROM cars GROUP BY trim(code) HAVING count(*) > 1;
   ```
   Должно вернуть 0 строк. По read-only `/api/cars` от 14.11.2026 — 12 разных кодов, дублей не видно.
3. Триггер `auth_driver_assignment` на `cars` (смена водителя отзывает его сессии) и функция `fleetai_auth_revoke_driver()`.

Существующие данные не изменяются и не удаляются.

## Шаги выпуска

1. **Резервная копия базы** (`scripts/backup_database.sh` с production `DATABASE_URL`), проверить, что файл создан и `pg_restore --list` прошёл. Без копии не продолжать.
2. **Проверка дублей кодов** — SQL выше.
3. **Настройки Render** (Environment, сервис production) — задать до слияния:
   - `FLEETAI_PUBLIC_BASE_URL=https://fleetai-1.onrender.com` — без неё вход всегда отклоняется.
   - `TELEGRAM_WEBHOOK_SECRET=<новая случайная строка>` — без неё бот перестанет принимать сообщения (503). После выпуска перерегистрировать webhook с этим секретом.
   - `CRON_SECRET=<новая случайная строка>` — и прописать его в Render Cron (заголовок `X-Admin-Secret`).
   - `WIALON_665_UNIT_ID=50613` — актуальный трекер 665 (сейчас там несуществующий #49896).
4. **CI зелёный** в PR (`Tests`, `Agent fast checks`).
5. **Слияние PR в `main`** — только по команде владельца.
6. **Пароль владельца** — в Render Shell сервиса:
   ```sh
   flask --app app auth bootstrap-owner --username <имя>
   ```
   Пароль вводится скрыто, нигде не сохраняется в открытом виде.
7. **Проверка после выпуска:**
   - `https://fleetai-1.onrender.com/api/cars` без входа → 401;
   - вход через `/auth/login` → открывается главная;
   - `/monitor` → карта, машины с трекером на местах;
   - бот Telegram отвечает; cron прошёл по расписанию.

## Откат

| Ситуация | Действие |
|---|---|
| Приложение не стартует / сломан вход | Render → Deploys → «Rollback» на предыдущий деплой (код `main` до слияния). Новые таблицы, индекс и триггер старому коду не мешают. |
| Мешает триггер или индекс | `DROP TRIGGER IF EXISTS auth_driver_assignment ON cars; DROP FUNCTION IF EXISTS fleetai_auth_revoke_driver(); DROP INDEX IF EXISTS auth_car_code_trim_unique;` |
| Повреждены данные | Восстановить из копии шага 1 (`scripts/restore_database.sh`) — только по решению владельца. |
| Не работает бот | Проверить `TELEGRAM_WEBHOOK_SECRET` и повторно зарегистрировать webhook. |

Revert-коммит в `main` — альтернатива откату в Render, если нужно сохранить историю.
