import sqlite3

def execute_sql_file(file_path, db_path):
    with open(file_path, 'r') as sql_file:
        sql_script = sql_file.read()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(sql_script)
    conn.commit()
    conn.close()

execute_sql_file('/app/backend/create_tables.sql', '/app/backend/data/webui.db')