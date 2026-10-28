#!/usr/bin/env python3

import sqlite3
from sqlalchemy import inspect, MetaData
from open_webui.internal.db import Base

# Подключение к базе данных SQLite
conn = sqlite3.connect('/app/backend/data/webui.db')

# Используем SQLAlchemy для инспекции таблиц
metadata = MetaData()
metadata.reflect(bind=conn)

# Выводим список всех таблиц
print("Список таблиц в базе данных:")
for table_name in metadata.tables.keys():
    print(f"- {table_name}")

# Выводим структуру каждой таблицы
print("\nСтруктура таблиц:")
for table_name in metadata.tables.keys():
    table = metadata.tables[table_name]
    print(f"\nТаблица: {table_name}")
    for column in table.columns:
        print(f"  - {column.name}: {column.type}")

# Закрываем соединение
conn.close()