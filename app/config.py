"""
Configuration settings for the Flask application.
"""
import os
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(basedir), '.env'))


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
    
    # External sentiment analysis API
    # Prefer SENTIMENT_API_URL, fall back to MODAL_ML_BASE_URL for compatibility
    SENTIMENT_API_URL = os.environ.get('SENTIMENT_API_URL') or os.environ.get('MODAL_ML_BASE_URL')
    
    # Flask settings
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    TESTING = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Server configuration for URL generation in emails
    SERVER_NAME = os.environ.get('SERVER_NAME')
    APPLICATION_ROOT = os.environ.get('APPLICATION_ROOT', '/')
    PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME', 'https')

    # Database
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        # Railway uses postgres:// but SQLAlchemy needs postgresql://
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    # If using Railway's internal Postgres and DB name isn't 'railway',
    # assume the default DB name 'railway' (common case) to avoid "does not exist" errors
    try:
        if database_url:
            parsed = urlparse(database_url)
            host = parsed.hostname
            dbname = (parsed.path or '').lstrip('/')
            if host == 'postgres.railway.internal' and dbname and dbname != 'railway':
                corrected = urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    '/railway',
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
                database_url = corrected
                # Keep process env consistent for downstream users
                os.environ['DATABASE_URL'] = database_url
    except Exception:
        # Best-effort; if parsing fails, continue with original URL
        pass
    
    # Prefer psycopg3 driver if available
    try:
        import psycopg  # noqa: F401
        if database_url and database_url.startswith('postgresql://'):
            database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    except Exception:
        # psycopg not installed; fallback to default driver (psycopg2)
        pass

    SQLALCHEMY_DATABASE_URI = database_url or \
        'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Rate limiting settings (for future implementation)
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL') or 'memory://'
    
    # Application settings - Tiered comment limits
    MAX_COMMENTS_ANONYMOUS = int(os.environ.get('MAX_COMMENTS_ANONYMOUS', 2500))  # Free tier - anonymous users
    MAX_COMMENTS_FREE = int(os.environ.get('MAX_COMMENTS_FREE', 5000))  # Free tier - logged in users
    MAX_COMMENTS_PRO = int(os.environ.get('MAX_COMMENTS_PRO', 50000))  # Pro tier - subscribers
    MAX_COMMENTS_PER_VIDEO = int(os.environ.get('MAX_COMMENTS_PER_VIDEO', 50000))  # Absolute max
    MAX_COMMENTS_PREVIEW = int(os.environ.get('MAX_COMMENTS_PREVIEW', 500))  # Fast preview mode
    CACHE_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT', 300))  # 5 minutes
    
    # API Performance settings
    API_TIMEOUT = int(os.environ.get('API_TIMEOUT', 30))  # Timeout for external API calls
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 4))  # For async operations

    # Payments (Stripe only)
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID')  # Monthly price id (introductory: $10, regular: $20)
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    # Email Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USERNAME)

    # Google OAuth (Login)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    # Optional: override the computed redirect URI
    OAUTH_REDIRECT_URI = os.environ.get('OAUTH_REDIRECT_URI')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    WTF_CSRF_ENABLED = False


config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': ProductionConfig
}
