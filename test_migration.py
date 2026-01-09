"""
Test script to verify database migration
Run this to check if the show_rating_scale column exists
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.database import engine, SessionLocal
from sqlalchemy import text, inspect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_column():
    """Check if show_rating_scale column exists"""
    db = SessionLocal()
    try:
        # Check if table exists
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'questions' not in tables:
            print("❌ Questions table doesn't exist!")
            return False
        
        print("✅ Questions table exists")
        
        # Check if column exists
        columns = [col['name'] for col in inspector.get_columns('questions')]
        
        if 'show_rating_scale' in columns:
            print("✅ show_rating_scale column exists!")
            
            # Check the column type
            for col in inspector.get_columns('questions'):
                if col['name'] == 'show_rating_scale':
                    print(f"   Column type: {col['type']}")
                    print(f"   Default value: {col.get('default', 'None')}")
                    print(f"   Nullable: {col.get('nullable', 'Unknown')}")
            return True
        else:
            print("❌ show_rating_scale column does NOT exist")
            print(f"   Existing columns: {', '.join(columns)}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking column: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("Checking database migration status...")
    print("-" * 50)
    success = check_column()
    print("-" * 50)
    if success:
        print("✅ Migration is complete!")
    else:
        print("❌ Migration needed. Run: python migrate_database.py")
    sys.exit(0 if success else 1)

