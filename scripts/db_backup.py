#!/usr/bin/env python
"""
Database backup script for Sentiment Analyzer.
Supports both SQLite (local) and PostgreSQL (Railway production).
"""
import os
import sys
import subprocess
import shutil
import gzip
from datetime import datetime
from urllib.parse import urlparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.config import Config


class DatabaseBackup:
    def __init__(self):
        self.app = create_app()
        self.db_url = self.app.config.get('SQLALCHEMY_DATABASE_URI')
        self.db_type = self._get_db_type()
        if self.db_type == 'sqlite' and '/data/' in (self.db_url or ''):
            self.backup_dir = '/data/backups'
        else:
            self.backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        os.makedirs(self.backup_dir, exist_ok=True)
        
    def _get_db_type(self):
        """Determine database type from URL."""
        if self.db_url.startswith('sqlite'):
            return 'sqlite'
        elif self.db_url.startswith('postgresql') or self.db_url.startswith('postgres'):
            return 'postgresql'
        else:
            raise ValueError(f"Unsupported database type: {self.db_url}")
    
    def _get_backup_filename(self, extension='sql'):
        """Generate backup filename with timestamp."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        env = os.environ.get('FLASK_ENV', 'development')
        return f"backup_{env}_{timestamp}.{extension}"
    
    def backup_sqlite(self):
        """Backup SQLite database."""
        # Extract database path from URL
        db_path = self.db_url.replace('sqlite:///', '')
        
        if not os.path.exists(db_path):
            print(f"❌ Database file not found: {db_path}")
            return False
        
        # Create backup filename
        backup_filename = self._get_backup_filename('db')
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        try:
            # Copy database file
            shutil.copy2(db_path, backup_path)
            
            # Compress the backup
            compressed_path = f"{backup_path}.gz"
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed backup
            os.remove(backup_path)
            
            # Get file size
            size_mb = os.path.getsize(compressed_path) / (1024 * 1024)
            
            print(f"✅ SQLite backup created successfully!")
            print(f"   Location: {compressed_path}")
            print(f"   Size: {size_mb:.2f} MB")
            
            return compressed_path
            
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False
    
    def backup_postgresql(self):
        """Backup PostgreSQL database using pg_dump."""
        # Parse database URL
        parsed = urlparse(self.db_url)
        
        # Extract connection details
        db_name = parsed.path[1:]  # Remove leading '/'
        db_user = parsed.username
        db_pass = parsed.password
        db_host = parsed.hostname
        db_port = parsed.port or 5432
        
        # Create backup filename
        backup_filename = self._get_backup_filename('sql')
        backup_path = os.path.join(self.backup_dir, backup_filename)
        compressed_path = f"{backup_path}.gz"
        
        # Set PostgreSQL password as environment variable
        env = os.environ.copy()
        if db_pass:
            env['PGPASSWORD'] = db_pass
        
        try:
            # Build pg_dump command
            cmd = [
                'pg_dump',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', db_name,
                '--no-owner',
                '--no-privileges',
                '--if-exists',
                '--clean',
                '-f', backup_path
            ]
            
            print(f"Creating PostgreSQL backup from {db_host}...")
            
            # Run pg_dump
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"❌ pg_dump failed: {result.stderr}")
                return False
            
            # Compress the backup
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed backup
            os.remove(backup_path)
            
            # Get file size
            size_mb = os.path.getsize(compressed_path) / (1024 * 1024)
            
            print(f"✅ PostgreSQL backup created successfully!")
            print(f"   Location: {compressed_path}")
            print(f"   Size: {size_mb:.2f} MB")
            
            return compressed_path
            
        except FileNotFoundError:
            print("❌ pg_dump not found. Please install PostgreSQL client tools:")
            print("   macOS: brew install postgresql")
            print("   Ubuntu/Debian: apt-get install postgresql-client")
            print("   RHEL/CentOS: yum install postgresql")
            return False
        except Exception as e:
            print(f"❌ Backup failed: {e}")
            return False
    
    def backup(self):
        """Perform database backup based on database type."""
        print(f"Starting backup for {self.db_type} database...")
        print(f"Backup directory: {self.backup_dir}")
        
        if self.db_type == 'sqlite':
            return self.backup_sqlite()
        elif self.db_type == 'postgresql':
            return self.backup_postgresql()
    
    def list_backups(self):
        """List all available backups."""
        backups = []
        for filename in os.listdir(self.backup_dir):
            if filename.startswith('backup_') and filename.endswith('.gz'):
                filepath = os.path.join(self.backup_dir, filename)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                backups.append({
                    'filename': filename,
                    'path': filepath,
                    'size_mb': size_mb,
                    'created': mtime
                })
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x['created'], reverse=True)
        
        if backups:
            print(f"\n📦 Available backups ({len(backups)} total):")
            print("-" * 70)
            for backup in backups:
                print(f"  {backup['filename']:<50} {backup['size_mb']:>6.2f} MB  {backup['created'].strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("No backups found.")
        
        return backups
    
    def cleanup_old_backups(self, keep_count=10):
        """Remove old backups, keeping only the most recent ones."""
        backups = self.list_backups()
        
        if len(backups) <= keep_count:
            print(f"✅ No cleanup needed. {len(backups)} backups found (keeping {keep_count}).")
            return
        
        to_delete = backups[keep_count:]
        
        print(f"\n🗑️  Cleaning up old backups (keeping {keep_count} most recent)...")
        for backup in to_delete:
            try:
                os.remove(backup['path'])
                print(f"   Deleted: {backup['filename']}")
            except Exception as e:
                print(f"   Failed to delete {backup['filename']}: {e}")
        
        print(f"✅ Cleanup complete. Removed {len(to_delete)} old backups.")


def main():
    """Main function with CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Database backup utility')
    parser.add_argument('action', choices=['backup', 'list', 'cleanup'],
                      help='Action to perform')
    parser.add_argument('--keep', type=int, default=10,
                      help='Number of backups to keep during cleanup (default: 10)')
    
    args = parser.parse_args()
    
    backup_manager = DatabaseBackup()
    
    if args.action == 'backup':
        backup_manager.backup()
        # Auto-cleanup after backup
        backup_manager.cleanup_old_backups(args.keep)
    elif args.action == 'list':
        backup_manager.list_backups()
    elif args.action == 'cleanup':
        backup_manager.cleanup_old_backups(args.keep)


if __name__ == '__main__':
    main()
