#!/usr/bin/env python
"""
Script to run database migrations on Railway production.
Run this script in Railway's shell or as a one-off command after deployment.
"""

import os
import sys
from flask_migrate import upgrade
from app import create_app

def run_migration():
    """Apply Alembic migrations. This script does not change anyone's subscription."""
    print("Starting database migration...")
    app = create_app()
    with app.app_context():
        try:
            upgrade()
            print("Migration completed successfully.")
        except Exception as e:
            print(f"Migration failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    run_migration()