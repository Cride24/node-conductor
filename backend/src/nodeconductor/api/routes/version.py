from fastapi import APIRouter

from nodeconductor.core.config import settings

router = APIRouter()


@router.get("/api/v1/version")
def version():
    """
    Versioncheck MVP.

    Pour l'instant on ne fait que refléter :
    - nom de l'application
    - la version du backend
    - la version de l'API
    """

    return {
        "name": settings.name,
        "app_version": settings.version,
        "api_version": settings.api_version
    }