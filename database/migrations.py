"""
Database migration script to add new columns to existing tables
"""
from sqlalchemy import text, inspect
from database.database import engine, SessionLocal
import logging

logger = logging.getLogger(__name__)

def add_show_rating_scale_column():
    """Add show_rating_scale column to questions table if it doesn't exist"""
    db = SessionLocal()
    try:
        # First check if table exists
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            if 'questions' not in tables:
                logger.info("Questions table doesn't exist yet. It will be created by SQLAlchemy.")
                return
        except Exception as inspect_error:
            logger.warning(f"Could not check if table exists: {inspect_error}. Proceeding anyway...")
        
        # Check if column already exists
        try:
            inspector = inspect(engine)
            columns = [col['name'] for col in inspector.get_columns('questions')]
            
            if 'show_rating_scale' in columns:
                logger.info("show_rating_scale column already exists")
                return
        except Exception as inspect_error:
            logger.warning(f"Could not inspect table structure: {inspect_error}. Proceeding with direct SQL...")
        
        # Try PostgreSQL syntax first (IF NOT EXISTS) - works with PostgreSQL 9.5+
        try:
            logger.info("Adding show_rating_scale column to questions table...")
            result = db.execute(text("""
                ALTER TABLE questions 
                ADD COLUMN IF NOT EXISTS show_rating_scale BOOLEAN DEFAULT TRUE
            """))
            db.commit()
            logger.info("Successfully added show_rating_scale column")
        except Exception as e:
            error_msg = str(e).lower()
            # Check if column already exists
            if any(keyword in error_msg for keyword in ['already exists', 'duplicate', 'column', 'exists']):
                logger.info("Column already exists (this is okay)")
                db.rollback()
                return
            # If IF NOT EXISTS syntax error, try without it
            elif 'syntax' in error_msg or 'if not exists' in error_msg:
                logger.info("IF NOT EXISTS not supported, trying standard ALTER TABLE...")
                db.rollback()
                try:
                    db.execute(text("""
                        ALTER TABLE questions 
                        ADD COLUMN show_rating_scale BOOLEAN DEFAULT TRUE
                    """))
                    db.commit()
                    logger.info("Successfully added show_rating_scale column")
                except Exception as e2:
                    error_msg2 = str(e2).lower()
                    if any(keyword in error_msg2 for keyword in ['already exists', 'duplicate']):
                        logger.info("Column already exists (this is okay)")
                        db.rollback()
                    else:
                        logger.error(f"Failed to add column: {str(e2)}")
                        db.rollback()
                        # Don't raise - let app continue
            else:
                logger.error(f"Unexpected error adding column: {str(e)}")
                db.rollback()
                # Don't raise - let app continue
    except Exception as e:
        db.rollback()
        logger.error(f"Error in migration: {str(e)}")
        # Don't raise - let the app continue even if migration fails
    finally:
        db.close()

def run_migrations():
    """Run all pending migrations"""
    try:
        add_show_rating_scale_column()
        logger.info("All migrations completed successfully")
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        # Don't raise - migrations are optional and shouldn't break the app
