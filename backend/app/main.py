"""
Entry point for Flask application.

When run via uvicorn (ASGI mode), the ``asgi_app`` object is used::

    uvicorn app.main:asgi_app --host 0.0.0.0 --port 8000

When run directly (``python app/main.py``), Flask's built-in dev server is used.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app import create_app, db

app = create_app()

# Create tables if they don't exist
with app.app_context():
    db.create_all()

# Wrap the Flask WSGI app with WsgiToAsgi so that uvicorn can serve it
# in full ASGI mode.  This allows a single worker to handle many concurrent
# streaming connections (critical for AI gateway workloads).
from asgiref.wsgi import WsgiToAsgi

asgi_app = WsgiToAsgi(app)


if __name__ == '__main__':
    # Run development server
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 8000)),
        debug=os.getenv('DEBUG', 'true').lower() == 'true'
    )
