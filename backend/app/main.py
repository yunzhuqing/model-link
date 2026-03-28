"""
Entry point for Flask application.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app import create_app, db

app = create_app()

# Create tables if they don't exist, then seed built-in model templates
with app.app_context():
    db.create_all()
    from app.routes.model_templates import seed_builtin_templates
    seed_builtin_templates()


if __name__ == '__main__':
    # Run development server
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 8000)),
        debug=os.getenv('DEBUG', 'true').lower() == 'true'
    )