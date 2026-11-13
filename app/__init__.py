"""
YouTube Sentiment Analyzer Flask Application
Modified to preload ML models at startup for better performance on Railway
"""
import os
import logging
import threading
import hmac
from datetime import datetime
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from app.config import Config

# Initialize extensions (without app)
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

logger = logging.getLogger(__name__)


def preload_models():
    """Deprecated - ML models now handled by external service."""
    logger.info("Model preloading skipped - using external sentiment API")
    return


def create_app(config_class=Config):
    """Application factory pattern for Flask app creation."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # On Railway, disable strict server name matching to allow healthchecks from
    # healthcheck.railway.app and other internal hosts
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        app.config['SERVER_NAME'] = None

    # Setup logging
    if not app.debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    # Enable CORS for all routes
    if app.config.get('DEBUG', False):
        CORS(app, origins=['http://localhost:3000', 'http://localhost:3002'])
    else:
        CORS(app, origins=['https://web-production-6a064.up.railway.app'])

    # Fail-closed HTTP Basic authentication for private deployments.
    @app.before_request
    def require_private_admin():
        if request.path == '/healthz':
            return None
        expected_user = os.environ.get('ADMIN_USERNAME', '')
        expected_pass = os.environ.get('ADMIN_PASSWORD', '')
        if not expected_user or not expected_pass:
            return Response('Admin authentication not configured', status=503)
        auth = request.authorization
        if not auth or not (
            hmac.compare_digest(auth.username or '', expected_user)
            and hmac.compare_digest(auth.password or '', expected_pass)
        ):
            return Response(
                'Administrator authentication required',
                status=401,
                headers={'WWW-Authenticate': 'Basic realm="Private Admin"'}
            )
        return None

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Initialize Flask-Mail
    from app.email import mail
    mail.init_app(app)

    # Register custom Jinja2 filters
    from app.filters import register_filters
    register_filters(app)

    # Register blueprints
    from app.main import bp as main_bp
    app.register_blueprint(main_bp)
    
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    from app.main.channel_routes import bp as channel_bp
    app.register_blueprint(channel_bp)

    # Import models for migrations
    with app.app_context():
        try:
            from app.models import User  # noqa: F401
            # Avoid database initialization on Railway to prevent startup blocking
            if not os.environ.get('RAILWAY_ENVIRONMENT') and os.environ.get('DB_INIT_ON_START', 'false').lower() == 'true':
                # Create tables if they don't exist (for local development only)
                db.create_all()
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")

    # Model preloading is deprecated - using external sentiment API

    # Background warmup is deprecated - using external sentiment API

    # Add health check endpoint for Railway
    @app.route('/health')
    def health_check():
        """Health check endpoint for Railway."""
        # Basic health check - just verify the app is running
        health_status = {
            'status': 'healthy',
            'environment': os.environ.get('RAILWAY_ENVIRONMENT', 'local'),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Try to check database (but don't fail if it's not ready)
        try:
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            health_status['database'] = 'connected'
        except Exception as e:
            health_status['database'] = f'initializing'
            logger.info(f"Database not ready yet: {e}")
        
        # Check sentiment API status
        health_status['sentiment_api'] = 'external'

        
        # Always return 200 OK for basic health
        return jsonify(health_status), 200

    # Minimal liveness endpoint for platform health checks
    @app.route('/healthz')
    def healthz():
        return jsonify({'ok': True}), 200

    # Add API stats endpoint (for debugging)
    @app.route('/api/stats')
    def api_stats():
        """Get API statistics."""
        return {
            'sentiment_api': 'external',
            'api_timeout': app.config.get('API_TIMEOUT', 30)
        }, 200

    return app
