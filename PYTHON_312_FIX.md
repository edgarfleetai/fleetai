# Исправление Render Python 3.14

Ошибка была из-за Python 3.14 и psycopg2.

Добавлен файл:

```text
runtime.txt
```

С содержимым:

```text
python-3.12.7
```

Теперь Render будет собирать проект на Python 3.12.
