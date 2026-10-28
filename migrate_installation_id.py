#!/usr/bin/env python3

import sys
import logging
from sqlalchemy import text, inspect
from open_webui.internal.db import engine

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def migrate_installation_id_column():
    """Миграция для добавления столбца installation_id в таблицу coder_github_connection"""
    try:
        # Проверяем, существует ли таблица
        inspector = inspect(engine)
        if 'coder_github_connection' not in inspector.get_table_names():
            log.error("Таблица coder_github_connection не существует!")
            return False
            
        # Проверяем, существует ли столбец installation_id
        columns = inspector.get_columns('coder_github_connection')
        column_names = [col['name'] for col in columns]
        
        if 'installation_id' in column_names:
            log.info("Столбец installation_id уже существует!")
            return True
            
        # Если столбец отсутствует, создаем новую таблицу с правильной структурой
        log.info("Столбец installation_id отсутствует. Начинаем миграцию...")
        
        # Получаем список всех столбцов
        existing_columns = [col['name'] for col in columns]
        
        # Создаем SQL для создания временной таблицы
        create_temp_table_sql = f"""
        CREATE TABLE coder_github_connection_temp (
            {', '.join([f'{col} TEXT' for col in existing_columns])},
            installation_id TEXT
        )
        """
        
        # Выполняем миграцию
        with engine.connect() as conn:
            # Создаем временную таблицу
            conn.execute(text(create_temp_table_sql))
            
            # Копируем данные из старой таблицы в новую
            columns_list = ', '.join(existing_columns)
            copy_data_sql = f"INSERT INTO coder_github_connection_temp ({columns_list}) SELECT {columns_list} FROM coder_github_connection"
            conn.execute(text(copy_data_sql))
            
            # Удаляем старую таблицу
            conn.execute(text('DROP TABLE coder_github_connection'))
            
            # Переименовываем временную таблицу
            conn.execute(text('ALTER TABLE coder_github_connection_temp RENAME TO coder_github_connection'))
            
            conn.commit()
            log.info("✅ Миграция завершена успешно!")
            return True
            
    except Exception as e:
        log.error(f"❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = migrate_installation_id_column()
    sys.exit(0 if success else 1)