#!/usr/bin/env python
"""
Entry point for the YouTube Sentiment Analyzer Flask application.
"""
import os
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fix Railway's postgres:// URL if needed
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith('postgres://'):
    os.environ['DATABASE_URL'] = db_url.replace('postgres://', 'postgresql://', 1)
    logger.info("Fixed DATABASE_URL for PostgreSQL compatibility")

# Log sanitized DB target to aid debugging (no credentials)
try:
    from urllib.parse import urlparse
    parsed = urlparse(os.environ.get('DATABASE_URL', ''))
    host = parsed.hostname
    dbname = (parsed.path or '').lstrip('/')
    if host and dbname:
        logger.info(f"Database target: host={host}, db={dbname}")
except Exception:
    pass

from app import create_app, db
from app.models import User
from app.config import config_dict

# Get configuration from environment or use default
config_name = os.environ.get('FLASK_ENV', 'production').lower()
config_class = config_dict.get(config_name, config_dict['production'])
app = create_app(config_class)

# Optionally ensure database tables exist (disabled by default in production)
with app.app_context():
    try:
        if not os.environ.get('RAILWAY_ENVIRONMENT') and os.environ.get('DB_INIT_ON_START', 'false').lower() == 'true':
            db.create_all()
            logger.info("Database tables ready (local init)")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

if __name__ == '__main__':
    # Run the application
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 8000)),
        debug=app.config.get('DEBUG', False)
    )
