from logging.config import fileConfig
import os
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from pathlib import Path
import sys
from importlib import import_module
from sqlmodel import SQLModel as _SQLModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Ensure the repository root is on sys.path so alembic can import the backend package
ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    # insert at the front so local packages take precedence over site-packages
    sys.path.insert(0, ROOT_STR)

# Ensure model modules are imported so SQLModel metadata is populated for autogenerate
# Import as a module for side-effects; keep reference to avoid "imported but unused" warnings
_models_module = import_module("backend.app.models")

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = _SQLModel.metadata

# other values from the config, defined by the needs of env.py, can be acquired:
# ... etc.
DATABASE_URL = os.getenv('DATABASE_URL', config.get_main_option('sqlalchemy.url'))


def run_migrations_offline():
    url = DATABASE_URL
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online())
