"""
Standalone database migration script
Run this script to add the show_rating_scale column to the questions table
Usage: python migrate_database.py
"""
import sys
import os

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.migrations import run_migrations
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    print("Running database migrations...")
    try:
        run_migrations()
        print("✅ Migrations completed successfully!")
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        sys.exit(1)

