#!/usr/bin/env python
"""
Database restore script for Sentiment Analyzer.
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

from app import create_app, db
from app.config import Config


class DatabaseRestore:
    def __init__(self):
        self.app = create_app()
        self.db_url = self.app.config.get('SQLALCHEMY_DATABASE_URI')
        self.db_type = self._get_db_type()
        volume_backups = '/data/backups'
        project_backups = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        self.backup_dir = volume_backups if os.path.isdir(volume_backups) else project_backups
    
    def _get_db_type(self):
        """Determine database type from URL."""
        if self.db_url.startswith('sqlite'):
            return 'sqlite'
        elif self.db_url.startswith('postgresql') or self.db_url.startswith('postgres'):
            return 'postgresql'
        else:
            raise ValueError(f"Unsupported database type: {self.db_url}")
    
    def list_available_backups(self):
        """List all available backup files."""
        if not os.path.exists(self.backup_dir):
            print(f"❌ Backup directory not found: {self.backup_dir}")
            return []
        
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
        return backups
    
    def select_backup(self, backup_file=None):
        """Select a backup file to restore."""
        if backup_file:
            # Use specified backup file
            if not os.path.isabs(backup_file):
                backup_file = os.path.join(self.backup_dir, backup_file)
            
            if not os.path.exists(backup_file):
                print(f"❌ Backup file not found: {backup_file}")
                return None
            
            return backup_file
        
        # List available backups and let user choose
        backups = self.list_available_backups()
        
        if not backups:
            print("❌ No backup files found.")
            return None
        
        print("\n📦 Available backups:")
        print("-" * 70)
        for i, backup in enumerate(backups, 1):
            print(f"  {i}. {backup['filename']:<45} {backup['size_mb']:>6.2f} MB  {backup['created'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get user choice
        while True:
            try:
                choice = input("\nEnter backup number to restore (or 'q' to quit): ")
                if choice.lower() == 'q':
                    return None
                
                idx = int(choice) - 1
                if 0 <= idx < len(backups):
                    return backups[idx]['path']
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
    
    def decompress_backup(self, backup_path):
        """Decompress a gzipped backup file."""
        if not backup_path.endswith('.gz'):
            return backup_path
        
        decompressed_path = backup_path[:-3]  # Remove .gz extension
        
        print(f"Decompressing backup...")
        with gzip.open(backup_path, 'rb') as f_in:
            with open(decompressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        return decompressed_path
    
    def restore_sqlite(self, backup_path):
        """Restore SQLite database from backup."""
        # Extract database path from URL
        db_path = self.db_url.replace('sqlite:///', '')
        
        # Create backup of current database
        if os.path.exists(db_path):
            current_backup = f"{db_path}.before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(db_path, current_backup)
            print(f"✓ Created backup of current database: {current_backup}")
        
        try:
            # Decompress if needed
            decompressed_path = self.decompress_backup(backup_path)
            
            # Restore database
            shutil.copy2(decompressed_path, db_path)
            
            # Clean up decompressed file if it was created
            if decompressed_path != backup_path:
                os.remove(decompressed_path)
            
            print(f"✅ SQLite database restored successfully from {os.path.basename(backup_path)}")
            return True
            
        except Exception as e:
            print(f"❌ Restore failed: {e}")
            
            # Try to restore the backup we made
            if 'current_backup' in locals() and os.path.exists(current_backup):
                shutil.copy2(current_backup, db_path)
                print(f"✓ Restored original database from backup")
            
            return False
    
    def restore_postgresql(self, backup_path):
        """Restore PostgreSQL database from backup."""
        # Parse database URL
        parsed = urlparse(self.db_url)
        
        # Extract connection details
        db_name = parsed.path[1:]  # Remove leading '/'
        db_user = parsed.username
        db_pass = parsed.password
        db_host = parsed.hostname
        db_port = parsed.port or 5432
        
        # Set PostgreSQL password as environment variable
        env = os.environ.copy()
        if db_pass:
            env['PGPASSWORD'] = db_pass
        
        try:
            # Decompress if needed
            decompressed_path = self.decompress_backup(backup_path)
            
            print(f"Restoring PostgreSQL database on {db_host}...")
            
            # Build psql command
            cmd = [
                'psql',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', db_name,
                '-f', decompressed_path
            ]
            
            # Run psql
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            # Clean up decompressed file if it was created
            if decompressed_path != backup_path:
                os.remove(decompressed_path)
            
            if result.returncode != 0:
                print(f"❌ psql failed: {result.stderr}")
                return False
            
            print(f"✅ PostgreSQL database restored successfully from {os.path.basename(backup_path)}")
            return True
            
        except FileNotFoundError:
            print("❌ psql not found. Please install PostgreSQL client tools:")
            print("   macOS: brew install postgresql")
            print("   Ubuntu/Debian: apt-get install postgresql-client")
            print("   RHEL/CentOS: yum install postgresql")
            return False
        except Exception as e:
            print(f"❌ Restore failed: {e}")
            return False
    
    def restore(self, backup_file=None, force=False):
        """Restore database from backup."""
        # Select backup file
        backup_path = self.select_backup(backup_file)
        if not backup_path:
            print("Restore cancelled.")
            return False
        
        print(f"\n🔄 Preparing to restore from: {os.path.basename(backup_path)}")
        print(f"   Database type: {self.db_type}")
        print(f"   Target: {self.db_url}")
        
        # Confirm restore
        if not force:
            confirm = input("\n⚠️  WARNING: This will replace the current database. Continue? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("Restore cancelled.")
                return False
        
        # Perform restore based on database type
        if self.db_type == 'sqlite':
            return self.restore_sqlite(backup_path)
        elif self.db_type == 'postgresql':
            return self.restore_postgresql(backup_path)


def main():
    """Main function with CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Database restore utility')
    parser.add_argument('--backup', '-b', type=str,
                      help='Specific backup file to restore (optional)')
    parser.add_argument('--force', '-f', action='store_true',
                      help='Skip confirmation prompt')
    parser.add_argument('--list', '-l', action='store_true',
                      help='List available backups without restoring')
    
    args = parser.parse_args()
    
    restore_manager = DatabaseRestore()
    
    if args.list:
        backups = restore_manager.list_available_backups()
        if backups:
            print(f"\n📦 Found {len(backups)} backup(s)")
        else:
            print("No backups found.")
    else:
        restore_manager.restore(args.backup, args.force)


if __name__ == '__main__':
    main()
