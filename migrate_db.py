#!/usr/bin/env python3
"""
Database migration script to handle unique constraint removal and add user_id column
"""

import sqlite3
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Migrate database to remove unique constraint on email and add user_id column"""
    db_path = 'history.db'
    
    if not os.path.exists(db_path):
        logger.info("Database doesn't exist yet, no migration needed")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if users table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        if not cursor.fetchone():
            logger.info("Users table doesn't exist yet, no migration needed")
            conn.close()
            return
        
        # Check if summary_history table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summary_history';")
        if not cursor.fetchone():
            logger.info("Summary history table doesn't exist yet, no migration needed")
            conn.close()
            return
        
        # Get summary_history table schema
        cursor.execute("PRAGMA table_info(summary_history)")
        summary_columns = [col[1] for col in cursor.fetchall()]
        logger.info(f"Current summary_history schema: {summary_columns}")
        
        # Check if user_id column exists in summary_history
        if 'user_id' not in summary_columns:
            logger.info("Adding user_id column to summary_history table...")
            
            # Backup existing summary data
            cursor.execute("SELECT * FROM summary_history")
            existing_summaries = cursor.fetchall()
            logger.info(f"Found {len(existing_summaries)} existing summary records")
            
            # Add user_id column
            cursor.execute("ALTER TABLE summary_history ADD COLUMN user_id INTEGER")
            logger.info("✅ Successfully added user_id column to summary_history")
            
        else:
            logger.info("✅ user_id column already exists in summary_history")
        
        # Get users table schema
        cursor.execute("PRAGMA table_info(users)")
        user_columns = cursor.fetchall()
        logger.info(f"Current users table schema: {user_columns}")
        
        # Check if we need to remove unique constraint on users table
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users';")
        create_sql = cursor.fetchone()[0]
        
        if 'UNIQUE' in create_sql.upper() and 'email' in create_sql.lower():
            logger.info("Removing unique constraint from users table...")
            
            # Create new users table without unique constraint
            cursor.execute("""
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    provider VARCHAR(50) NOT NULL DEFAULT 'google',
                    provider_id VARCHAR(255) NOT NULL,
                    avatar_url VARCHAR(500),
                    created_at DATETIME,
                    last_login DATETIME
                )
            """)
            
            # Copy data from old table
            logger.info("Copying data from old users table...")
            cursor.execute("""
                INSERT INTO users_new (id, email, name, provider, provider_id, avatar_url, created_at, last_login)
                SELECT id, email, name, provider, provider_id, avatar_url, created_at, last_login
                FROM users
            """)
            
            # Drop old table and rename new one
            logger.info("Replacing old users table...")
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_new RENAME TO users")
            
            # Create index on email for performance
            cursor.execute("CREATE INDEX idx_users_email ON users(email)")
            logger.info("✅ Successfully removed unique constraint from users table")
            
        else:
            logger.info("✅ Users table already has correct schema")
        
        # Verify final schema
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM summary_history")
        summary_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM summary_history WHERE user_id IS NULL")
        orphaned_summaries = cursor.fetchone()[0]
        
        logger.info(f"\n📊 Database status:")
        logger.info(f"- Users: {user_count}")
        logger.info(f"- Total summaries: {summary_count}")
        logger.info(f"- Orphaned summaries (no user_id): {orphaned_summaries}")
        
        conn.commit()
        logger.info("🎉 Database migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()

def verify_database():
    """Verify the database structure after migration"""
    db_path = 'history.db'
    
    if not os.path.exists(db_path):
        logger.info("Database doesn't exist yet - it will be created on first run")
        return True
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Test that we can query with user_id
        cursor.execute("SELECT id, summary, original_url, created_at, user_id FROM summary_history LIMIT 1")
        logger.info("✅ Database schema verification successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database verification failed: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    logger.info("🔄 Starting database migration...")
    logger.info(f"📍 Working directory: {os.getcwd()}")
    
    migrate_database()
    if verify_database():
        logger.info("\n🎉 Migration and verification completed successfully!")
        logger.info("You can now restart your Flask application.")
    else:
        logger.info("\n⚠️ Migration completed but verification failed.")
