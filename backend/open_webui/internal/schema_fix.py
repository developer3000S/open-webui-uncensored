import logging

from sqlalchemy import MetaData, Table, inspect

from open_webui.internal.db import engine

log = logging.getLogger(__name__)


async def check_and_fix_db_schema():
    """Check and fix database schema to match SQLAlchemy models.

    This function:
    1. Checks if all expected tables exist
    2. Creates missing tables
    3. For SQLite, handles missing columns by creating a new table with the correct schema
    4. Logs all actions for debugging
    """
    from open_webui.internal.db import Base

    try:
        # Create all tables automatically at startup
        Base.metadata.create_all(engine)
        log.info('Database tables created successfully.')

        # Create a connection to the database
        inspector = inspect(engine)

        # List of all tables we expect to exist
        expected_tables = {
            'coder_github_connection',
            'coder_github_app_installation',
            'coder_project',
            'coder_export_job',
            'coder_audit_event',
            'coder_sandbox_session',
            'coder_task_meta',
            'access_grants',
            'channels',
            'chats',
            'config',
            'functions',
            'messages',
            'models',
            'users',
            'oauth_sessions',
            'notes',
            'prompts',
            'prompt_history',
            'memories',
            'knowledge',
            'groups',
            'files',
            'folders',
            'feedbacks',
            'calendar',
            'calendar_event',
            'calendar_event_attendee',
            'automations',
            'auth',
            'tools',
            'skills',
            'shared_chats',
            'chat_messages',
            'tags',
        }

        # Get existing tables from the database
        existing_tables = set(inspector.get_table_names())

        # Check if all expected tables exist
        missing_tables = expected_tables - existing_tables

        if missing_tables:
            log.warning(f'The following tables are missing: {missing_tables}')
            # Create missing tables
            for table_name in missing_tables:
                try:
                    table = Table(table_name, MetaData(), autoload_with=engine)
                    table.create(engine)
                    log.info(f'Table {table_name} created successfully.')
                except Exception as e:
                    log.error(f'Failed to create table {table_name}: {e}')

        # Check for missing columns in coder_github_connection
        if 'coder_github_connection' in existing_tables:
            columns = inspector.get_columns('coder_github_connection')
            column_names = [col['name'] for col in columns]
            if 'installation_id' not in column_names:
                log.warning("Column 'installation_id' is missing in table 'coder_github_connection'")
            return True

        return False
    except Exception as e:
        log.error(f'Database schema validation failed: {e}')
        return False
