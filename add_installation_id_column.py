#!/usr/bin/env python3

import logging
from sqlalchemy import text
from open_webui.internal.db import engine

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def add_installation_id_column():
    """Добавляем столбец installation_id в таблицу coder_github_connection"""
    try:
        # Проверяем, существует ли таблица
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='coder_github_connection'"))
            table_exists = result.fetchone() is not None
            
            if not table_exists:
                log.error("Таблица coder_github_connection не существует!")
                return False
                
            # Проверяем, существует ли столбец
            result = conn.execute(text("PRAGMA table_info(coder_github_connection)"))
            columns = result.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'installation_id' in column_names:
                log.info("Столбец installation_id уже существует!")
                return True
                
            # Если столбец отсутствует, создаем новую таблицу с правильной структурой
            log.info("Столбец installation_id отсутствует. Начинаем миграцию...")
            
            # Получаем список всех существующих столбцов
            existing_columns = [col[1] for col in columns]
            
            # Создаем временную таблицу с правильной структурой
            create_temp_table_sql = """
            CREATE TABLE coder_github_connection_temp (
                id TEXT,
                user_id TEXT,
                github_login TEXT,
                github_user_id TEXT,
                github_host TEXT,
                access_token_encrypted TEXT,
                token_type TEXT,
                scopes TEXT,
                is_default INTEGER,
                installation_id TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
            """
            
            # Копируем данные из старой таблицы в новую
            copy_data_sql = """
            INSERT INTO coder_github_connection_temp (
                id, user_id, github_login, github_user_id, github_host, 
                access_token_encrypted, token_type, scopes, is_default, created_at, updated_at
            )
            SELECT {columns} FROM coder_github_connection
            """
            
            # Формируем SQL для копирования данных
            columns_list = ', '.join(existing_columns)
            copy_data_sql = copy_data_sql.format(columns=columns_list)
            
            # Выполняем миграцию
            conn.execute(text(create_temp_table_sql))
            conn.execute(text(copy_data_sql))
            
            # Удаляем старую таблицу
            conn.execute(text("DROP TABLE coder_github_connection"))
            
            # Переименовываем временную таблицу
            conn.execute(text("ALTER TABLE coder_github_connection_temp RENAME TO coder_github_connection"))
            
            conn.commit()
            log.info("Столбец installation_id успешно добавлен!")
            return True
            
    except Exception as e:
        log.error(f"Ошибка при добавлении столбца installation_id: {e}")
        return False

if __name__ == "__main__":
    success = add_installation_id_column()
    if success:
        print("\n✅ Успешно добавлен столбец installation_id!")
    else:
        print("\n❌ Не удалось добавить столбец installation_id!")