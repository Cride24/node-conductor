from contextlib import asynccontextmanager

from fastapi import FastAPI

from nodeconductor.services.worker_loop import WorkerLoopController
from nodeconductor.api.routes.health import router as health_router
from nodeconductor.api.routes.version import router as version_router
from nodeconductor.api.routes.services import router as services_router
from nodeconductor.api.routes.jobs import router as jobs_router
from nodeconductor.api.routes.events import router as events_router
from nodeconductor.core.config import settings
from nodeconductor.core.middleware import (
    RequestBodyLimitMiddleware,
    RequestTimeoutMiddleware,
)
from nodeconductor.services.events import record_system_started_event


worker_loop = WorkerLoopController(settings.worker_poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    record_system_started_event()
    if settings.worker_auto_enabled:
        worker_loop.start()
    yield
    await worker_loop.stop()


app = FastAPI(
    title="NodeConductor API",
    version=settings.api_version,
    lifespan=lifespan,
)
app.add_middleware(
    RequestTimeoutMiddleware,
    timeout_seconds=settings.api_request_timeout_seconds,
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.api_max_request_body_bytes,
)

# Les routers restent separes par domaine pour garder l'API v1 lisible.
app.include_router(health_router)
app.include_router(version_router)
app.include_router(services_router)
app.include_router(jobs_router)
app.include_router(events_router)
