from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from controller.user import router as user_router
from controller.admin import router as admin_router, create_default_admin
from database.database import engine, Base
from database.migrations import run_migrations
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Feedback API-----12",
    version="1.0.0",
    description="Automated AI feedback system for users and admins."
)

# Add CORS middleware BEFORE routers
# Allow all origins for production (Vercel deployment)
# Note: When allow_origins=["*"], allow_credentials must be False
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for production
    allow_credentials=False,  # Must be False when using "*"
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])


@app.on_event("startup")
async def startup_event():
    try:
        # Run database migrations FIRST (add new columns to existing tables)
        # This must run before create_all() to ensure columns exist
        run_migrations()
    except Exception as e:
        logger.warning(f"Could not run migrations: {e}. This is okay if columns already exist.")
    
    try:
        # Create database tables (only creates if they don't exist)
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.warning(f"Could not create database tables: {e}. Make sure PostgreSQL is running and accessible.")
    
    try:
        # Create default admin user
        create_default_admin()
        logger.info("Default admin user created/verified")
    except Exception as e:
        logger.warning(f"Could not create default admin user: {e}")

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }

    # Apply BearerAuth globally to all routes
    for path in openapi_schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
