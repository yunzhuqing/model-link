"""
Flask application factory for Model Link AI Gateway.
"""
from flask import Flask, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_httpauth import HTTPBasicAuth
import os

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
auth = HTTPBasicAuth()


def create_app(config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    
    # Load configuration
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///./sql_app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database connection pooling settings for long-lived connections
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,           # Number of connections to keep in the pool
        'max_overflow': 20,        # Maximum connections beyond pool_size
        'pool_timeout': 60,        # Timeout (seconds) for getting connection from pool
        'pool_recycle': 3600,      # Recycle connections after 1 hour (prevents MySQL gone away)
        'pool_pre_ping': True,     # Enable connection health checks
    }
    
    # Apply any custom config
    if config:
        app.config.update(config)
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app, resources={r"/*": {"origins": "*"}})
    
    # Register blueprints
    from app.routes.users import users_bp
    from app.routes.providers import providers_bp
    from app.routes.gateway import gateway_bp
    from app.routes.apikeys import apikeys_bp
    
    app.register_blueprint(users_bp)
    app.register_blueprint(providers_bp, url_prefix='/api')
    app.register_blueprint(gateway_bp)
    app.register_blueprint(apikeys_bp, url_prefix='/api')
    
    # Serve React frontend if static folder exists, otherwise API-only mode
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    static_dir = os.path.abspath(static_dir)

    if os.path.isdir(static_dir) and os.path.isfile(os.path.join(static_dir, 'index.html')):
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_react(path):
            """Serve React frontend. API routes take priority via blueprints."""
            # Serve static files (JS, CSS, images, etc.)
            if path and os.path.isfile(os.path.join(static_dir, path)):
                return send_from_directory(static_dir, path)
            # For all other routes, serve index.html (React Router handles client-side routing)
            return send_from_directory(static_dir, 'index.html')
    else:
        # API-only mode (no frontend build present)
        @app.route('/')
        def index():
            return {
                "message": "Welcome to AI Gateway API",
                "docs": "/docs",
                "endpoints": {
                    "openai_chat_completions": "/v1/chat/completions",
                    "anthropic_messages": "/v1/messages",
                    "openai_responses": "/v1/responses",
                    "models": "/v1/models",
                    "providers": "/api/providers/",
                    "register": "/register",
                    "login": "/token"
                }
            }

    @app.route('/health')
    def health():
        return {"status": "healthy"}
    
    return app
