import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.database import Base,engine
from app.models import entities  # noqa: F401
from app.api.routes import router
from app.core.config import openai_configuration_metadata
from app.services.copilot import close_provider_clients
from app.services.storage import storage_readiness

logger = logging.getLogger(__name__)
if settings.environment.lower() in {"development", "dev", "local"}:
    provider_configuration = openai_configuration_metadata()
    if (
        provider_configuration["process_environment_override_present"]
        and provider_configuration["dotenv_key_configured"]
        and not provider_configuration["settings_match_backend_dotenv"]
    ):
        logger.warning(
            "OPENAI_API_KEY from the process environment overrides a different "
            "backend .env value; the process environment credential will be used."
        )
if settings.auto_create_schema:
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_provider_clients()


app=FastAPI(title=settings.app_name,version="1.0.0",description="Business analytics, ML forecasting, anomaly detection and grounded AI copilot", lifespan=lifespan)
origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PATCH","DELETE"],allow_headers=["Authorization","Content-Type"],expose_headers=["X-Request-ID"])
app.include_router(router,prefix="/api/v1")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get('/health')
def health(): return {"status":"ok","service":"intellibiz-api","environment":settings.environment}

@app.get('/health/ready')
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Readiness check failed: database unavailable")
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    storage = storage_readiness()
    if storage["backend"] == "supabase" and storage["status"] != "ready":
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "database": "ok",
                "storage": storage,
            },
        )
    return {
        "status": "degraded" if storage["backend"] == "local" else "ready",
        "database": "ok",
        "storage": storage,
    }

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unavailable")
    logger.error(
        "Unhandled API error request_id=%s exception=%s",
        request_id,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )
