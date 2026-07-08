# FleetAI 2.0

Структура проекта:

- `app.py` — маршруты Flask
- `models.py` — таблицы базы
- `db.py` — подключение к PostgreSQL
- `migrations.py` — безопасное создание/обновление таблиц
- `parser.py` — разбор сообщений
- `finance.py` — финансы, периоды, инвесторы
- `templates.py` — интерфейс сайта

Запуск на Render:
Build Command:
`pip install -r requirements.txt`

Start Command:
`gunicorn app:app --bind 0.0.0.0:$PORT`

Environment:
`DATABASE_URL`
