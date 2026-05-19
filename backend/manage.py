"""
Management script for database migrations.

Since this project uses Quart (not Flask), the standard `flask db` CLI
does not work directly.  This script creates a lightweight Flask app
with the same database configuration and the same db/migrate instances
from app/__init__.py so that Alembic autogenerate can detect all models.

Usage (from the backend/ directory):

    FLASK_APP=manage.py uv run flask db current          # Show current revision
    FLASK_APP=manage.py uv run flask db migrate           # Generate migration
    FLASK_APP=manage.py uv run flask db upgrade           # Apply migrations
    FLASK_APP=manage.py uv run flask db downgrade         # Roll back
    FLASK_APP=manage.py uv run flask db history           # Show migration history
"""
import os
from dotenv import load_dotenv

# Load .env before importing app configuration
load_dotenv()

from flask import Flask

# Import the same db and migrate instances used by the Quart app
# This is critical — models in app.models reference `app.db`, so
# Alembic autogenerate must see the same SQLAlchemy instance.
from app import db, migrate


def create_app():
    """Create a Flask app with the same DB config as the Quart app."""
    app = Flask(__name__)

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///./sql_app.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": int(os.getenv("SQLALCHEMY_POOL_SIZE", 10)),
        "max_overflow": int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", 20)),
        "pool_timeout": int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", 30)),
        "pool_recycle": int(os.getenv("SQLALCHEMY_POOL_RECYCLE", 1800)),
        "pool_pre_ping": os.getenv("SQLALCHEMY_POOL_PRE_PING", "true").lower()
        == "true",
        "connect_args": {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", 10)),
            "read_timeout": int(os.getenv("DB_READ_TIMEOUT", 30)),
            "write_timeout": int(os.getenv("DB_WRITE_TIMEOUT", 30)),
        },
    }

    db.init_app(app)
    migrate.init_app(app, db)

    # Import all models so that Alembic autogenerate can detect them
    with app.app_context():
        from app import models  # noqa: F401

    return app


# Flask CLI picks this up when FLASK_APP=manage.py
app = create_app()