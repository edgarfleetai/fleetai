# FleetAI Cloud MVP

Облачная версия FleetAI. Работает локально и готова к размещению на сервере.

## Локальный запуск

```bash
pip install -r requirements.txt
python app.py
```

Откройте:

```text
http://127.0.0.1:8000
```

## Для облака

Приложение поддерживает:
- SQLite локально
- PostgreSQL через переменную `DATABASE_URL`

Команда запуска для сервера:

```bash
gunicorn app:app
```
