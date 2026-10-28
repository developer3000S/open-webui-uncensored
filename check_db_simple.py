#!/usr/bin/env python3

import sqlite3

# Подключение к базе данных SQLite
conn = sqlite3.connect('/app/backend/data/webui.db')

# Получение курсора
cursor = conn.cursor()

# Вывод списка всех таблиц
print("Список таблиц в базе данных:")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for table in tables:
    print(f"- {table[0]}")

# Вывод структуры каждой таблицы
print("\nСтруктура таблиц:")
for table in tables:
    table_name = table[0]
    print(f"\nТаблица: {table_name}")
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    for column in columns:
        print(f"  - {column[1]}: {column[2]}")

# Закрываем соединение
conn.close()