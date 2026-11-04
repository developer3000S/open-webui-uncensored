from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from open_webui.models import Base  # Импортируем базовые модели из приложения

# Настройка логов
fileConfig(context.config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    pass

def run_migrations_online():
    connectable = engine_from_config(
        context.config.get_section(context.config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()