from fastapi import FastAPI

from nodeconductor.api.routes.health import router as health_router
from nodeconductor.api.routes.version import router as version_router
from nodeconductor.api.routes.services import router as services_router
from nodeconductor.core.config import settings

app = FastAPI(title="NodeConductor API", version=settings.api_version)

app.include_router(health_router)
app.include_router(version_router)
app.include_router(services_router)