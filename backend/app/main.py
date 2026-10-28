from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.maintenance import MaintenanceMiddleware
from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.core.redis import close_redis
from app.services.admin import bootstrap_admins, parse_identifiers
from app.services.admin_backups import mark_interrupted_job

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initial_admins = parse_identifiers(get_settings().initial_admins)
    if initial_admins:
        async with SessionLocal() as session:
            await bootstrap_admins(session, initial_admins)
    await mark_interrupted_job()
    yield
    await close_redis()


app = FastAPI(
    title="Lecturo API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(MaintenanceMiddleware)
app.include_router(api_router)
