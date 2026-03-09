"""
Flask application factory for Model Link AI Gateway.
"""
from flask import Flask
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
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL', 
        'sqlite:///./sql_app.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Apply any custom config
    if config:
        app.config.update(config)
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app)
    
    # Register blueprints
    from app.routes.users import users_bp
    from app.routes.providers import providers_bp
    from app.routes.gateway import gateway_bp
    from app.routes.apikeys import apikeys_bp
    
    app.register_blueprint(users_bp)
    app.register_blueprint(providers_bp, url_prefix='/api')
    app.register_blueprint(gateway_bp)
    app.register_blueprint(apikeys_bp, url_prefix='/api')
    
    # Root endpoint
    @app.route('/')
    def index():
        return {
            "message": "Welcome to AI Gateway API",
            "docs": "/docs",
            "endpoints": {
                "openai_compatible": "/v1/chat/completions",
                "anthropic_compatible": "/v1/messages",
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