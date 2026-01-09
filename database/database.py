from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
load_dotenv()

# Try to use full connection string first, otherwise parse individual components
postgres_url = os.getenv("POSTGRES_URL")
if postgres_url:
    # If full URL is provided, use it directly (convert postgresql:// to postgresql+psycopg://)
    SQLALCHEMY_DATABASE_URL = postgres_url.replace("postgresql://", "postgresql+psycopg://")
else:
    # Otherwise, parse individual components
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT")
    database = os.getenv("POSTGRES_DB")
    
    # URL encode username and password to handle special characters
    encoded_user = quote_plus(user) if user else ""
    encoded_password = quote_plus(password) if password else ""
    SQLALCHEMY_DATABASE_URL = f"postgresql+psycopg://{encoded_user}:{encoded_password}@{host}:{port}/{database}"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create SQLAlchemy engine with connection pooling and lazy connection
# pool_pre_ping=True will verify connections before using them
# For Supabase, we need to handle connection errors gracefully
try:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=300,     # Recycle connections after 5 minutes
        connect_args={"connect_timeout": 10},  # 10 second connection timeout
        echo=False  # Set to True for SQL query debugging
    )
except Exception as e:
    print(f"Warning: Could not create database engine: {e}")
    print(f"Connection URL format: {SQLALCHEMY_DATABASE_URL[:50]}...")
    raise

# Create sessionmaker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declare the base class for the models
Base = declarative_base()


