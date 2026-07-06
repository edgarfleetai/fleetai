# FleetAI v0.3 CLEAN

Чистая версия для Render + PostgreSQL.

## Важно

В проекте больше нет `psycopg2-binary`. Используется `psycopg[binary]`.

## Render Environment

Нужна переменная:

```text
DATABASE_URL=<Internal Database URL из Render Postgres>
```

## Render Settings

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
gunicorn app:app
```

## Проверка

После деплоя:

```text
665 получил 1000
665 доп ГБО 35000р
665 стойка стаба AMD справа пробег 243000 стоимость 1000 ремонт 1000
```
