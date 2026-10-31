#!/usr/bin/env python3

import os
import sys
from pathlib import Path

# Добавляем путь к бэкенду в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

# Импортируем только необходимые модули
os.environ['WEBUI_SECRET_KEY'] = 'test-secret-key'

# Запускаем минимальное приложение FastAPI
if __name__ == "__main__":
    from fastapi import FastAPI
    from open_webui.config import setup_db
    from open_webui.main import create_app
    
    # Создаем приложение
    app = create_app()
    
    # Запускаем Uvicorn
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")