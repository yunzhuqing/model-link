"""
Entry point for Quart application.

Run via uvicorn (ASGI mode)::

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Or run directly (``python app/main.py``) for development.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app import create_app, db

app = create_app()

# Create tables if they don't exist (sync context, before server starts).
#
# Quart 0.20's app_context() is async-only, but Flask-SQLAlchemy's db.create_all()
# needs Flask's synchronous current_app proxy (via werkzeug's ContextVar).
# We set the ContextVar directly to bridge the gap.
from flask.globals import _cv_app
from flask.ctx import AppContext

_token = _cv_app.set(AppContext(app))
try:
    db.create_all()
finally:
    _cv_app.reset(_token)


if __name__ == '__main__':
    # Run development server
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 8000)),
        debug=os.getenv('DEBUG', 'true').lower() == 'true'
    )
