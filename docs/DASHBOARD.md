# FleetAI 4.0 — новый дашборд (отдельный сайт, только просмотр)

Код: `dashboard/` (Flask, один файл страницы `dashboard/static/index.html` в дизайне прототипа).
Старый FleetAI (`fleetai/`, сервис `fleetai-1`) не меняется и продолжает работать для ввода операций,
Telegram, cron и договоров.

## Что подключено

| Раздел | Источник | Статус |
|---|---|---|
| Главная | `cars` | ✅ статус парка, сданы в аренду, собственники, требуют внимания, мониторинг |
| Автомобили | `cars` | ✅ карточки, фильтры, таблица; баланс аренды — «не подключён» |
| Водители | `cars.driver` | ✅ кто на какой машине |
| Мониторинг | Wialon (token/login + core/search_items) | ✅ живые позиции, обновление каждые 30 с |
| Финансы, Инвесторы, Ремонты | — | «Раздел подключается»: цифры появятся после сверки со старым FleetAI |
| Аренда, Договоры, Задачи, Настройки | — | в разработке |

Тестовых данных на странице нет: всё, что не подключено, так и подписано.

## Безопасность
- **Только чтение.** Сессия PostgreSQL открывается с `default_transaction_read_only=on`; в production
  используется отдельная роль только с `SELECT` (ниже). В коде дашборда нет ни одного INSERT/UPDATE/DELETE (проверяется тестом).
- **Wialon:** клиент разрешает только `token/login` и `core/search_items`; любые команды машинам отклоняются в коде.
- **Вход:** тот же логин и пароль владельца, что в FleetAI (`auth_owners`), проверка хеша без записи в базу.
  Подписанная cookie `__Host-fa4` (Secure, HttpOnly, SameSite=Lax), 8 часов. Смена пароля в FleetAI завершает сессии дашборда.
  Не больше 5 неудачных попыток за 15 минут. Вход и выход защищены проверкой origin + CSRF.
- Заголовки: CSP (`connect-src 'self'`, `frame-ancestors 'none'`), HSTS, `X-Frame-Options: DENY`, `no-store`.

## Развёртывание (делает владелец)

**Выбрано владельцем 14.11.2026 — простой путь:** `DASHBOARD_DATABASE_URL` = тот же `DATABASE_URL`, что у `fleetai-1`.
Защита от записи в этом случае одна — сессия `default_transaction_read_only=on` и отсутствие записывающего SQL
в коде (тест). Отдельную роль (раздел 1) можно добавить позже, заменив только эту переменную.

### 1. (Необязательно) Роль только для чтения в Neon
Neon Console → проект → **SQL Editor** → ветка production (`import-2026-08-05T15:17:33.988Z`).
Пароль придумать заранее (или сгенерировать командой из `docs/RELEASE_LOGIN_AND_MONITOR.md`):
```sql
CREATE ROLE dashboard_ro WITH LOGIN PASSWORD '<пароль>';
GRANT CONNECT ON DATABASE neondb TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;
```
Роль создаётся именно через SQL, а не через раздел Roles: роли из консоли Neon получают права `neon_superuser`.
Проверка: `SELECT has_table_privilege('dashboard_ro', 'cars', 'INSERT');` → `false`.

Строка подключения: как у основной, но с пользователем `dashboard_ro` и его паролем.

### 2. Новый сервис в Render
**New → Web Service** → репозиторий `edgarfleetai/fleetai`, ветка `feature/dashboard-v4`
(после слияния PR — переключить на `main`; так production-сервис `fleetai-1` не передеплоивается ради дашборда).
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn dashboard.app:app --workers 1 --bind 0.0.0.0:$PORT`
- Health Check Path: `/healthz`
- Environment:
  - `DASHBOARD_DATABASE_URL` — значение `DATABASE_URL` из `fleetai-1` (или строка роли `dashboard_ro`)
  - `DASHBOARD_SECRET_KEY` — случайная строка 32+ символов
  - `DASHBOARD_PUBLIC_URL` — адрес сервиса, например `https://fleetai-dashboard.onrender.com`
  - `WIALON_TOKEN` — тот же, что у FleetAI

`--workers 1`: счётчик неудачных входов хранится в памяти процесса.

## Проверка
Тесты: `tests/test_dashboard_v4.py` (вход, отказ без входа, чужой origin, лимит попыток, отображение
реальных полей, сопоставление трекеров, отсутствие записей в базе, запрет команд Wialon, выход, заголовки).
Локальный просмотр на синтетических данных проверен в браузере: все разделы открываются, ошибок в консоли нет.
