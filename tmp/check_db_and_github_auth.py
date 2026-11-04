#!/usr/bin/env python3

import asyncio
import logging
from sqlalchemy import inspect, text
from open_webui.internal.db import engine
from open_webui.models.coder import CoderGithubConnection

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def check_db_schema():
    """Проверка схемы базы данных"""
    try:
        inspector = inspect(engine)
        
        # Проверка наличия таблицы coder_github_connection
        if 'coder_github_connection' not in inspector.get_table_names():
            log.error("Таблица coder_github_connection отсутствует!")
            return False
            
        # Проверка наличия столбца installation_id
        columns = inspector.get_columns('coder_github_connection')
        column_names = [col['name'] for col in columns]
        
        if 'installation_id' not in column_names:
            log.error("Столбец installation_id отсутствует в таблице coder_github_connection!")
            return False
            
        log.info("Схема базы данных проверена успешно!")
        log.info(f"Таблица coder_github_connection содержит следующие столбцы: {column_names}")
        return True
    except Exception as e:
        log.error(f"Ошибка при проверке схемы базы данных: {e}")
        return False

def check_github_auth_config():
    """Проверка конфигурации GitHub OAuth"""
    try:
        from open_webui.config import CODER_GITHUB_CLIENT_ID
        
        if not CODER_GITHUB_CLIENT_ID:
            log.error("GitHub OAuth не настроен: CODER_GITHUB_CLIENT_ID отсутствует!")
            return False
            
        log.info("GitHub OAuth настроен успешно!")
        return True
    except Exception as e:
        log.error(f"Ошибка при проверке конфигурации GitHub OAuth: {e}")
        return False

def check_github_connection_table():
    """Проверка содержимого таблицы coder_github_connection"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM coder_github_connection"))
            count = result.scalar()
            log.info(f"В таблице coder_github_connection содержится {count} записей")
            
            # Проверка наличия столбца installation_id в данных
            result = conn.execute(text("PRAGMA table_info(coder_github_connection)"))
            columns_info = result.fetchall()
            
            for col in columns_info:
                if col[1] == 'installation_id':
                    log.info(f"Столбец installation_id найден в таблице с типом: {col[2]}")
                    return True
            
            log.error("Столбец installation_id не найден в таблице")
            return False
    except Exception as e:
        log.error(f"Ошибка при проверке таблицы coder_github_connection: {e}")
        return False

async def main():
    """Основная функция проверки"""
    log.info("Начало проверки состояния системы...")
    
    # Проверка схемы базы данных
    db_ok = check_db_schema()
    
    # Проверка конфигурации GitHub OAuth
    auth_config_ok = check_github_auth_config()
    
    # Проверка таблицы coder_github_connection
    table_ok = check_github_connection_table()
    
    # Итоговый отчет
    log.info("\n=== ИТОГОВЫЙ ОТЧЕТ ===")
    log.info(f"Схема базы данных: {'OK' if db_ok else 'НЕИСПРАВНА'}")
    log.info(f"Конфигурация GitHub OAuth: {'OK' if auth_config_ok else 'НЕИСПРАВНА'}")
    log.info(f"Таблица coder_github_connection: {'OK' if table_ok else 'НЕИСПРАВНА'}")
    
    if db_ok and auth_config_ok and table_ok:
        log.info("\nВсе проверки пройдены успешно! GitHub авторизация должна работать корректно.")
    else:
        log.error("\nНекоторые проверки не пройдены. Пожалуйста, проверьте логи для деталей.")

if __name__ == "__main__":
    asyncio.run(main())