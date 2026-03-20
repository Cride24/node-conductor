from time import time

from fastapi import APIRouter

from nodeconductor.core.config import settings

router = APIRouter()

_process_start_time = time()


@router.get("/api/v1/health")
def health():
    """
    Healthcheck MVP.

    Pour l'instant on ne fait que refléter :
    - un statut global
    - la version
    - l'uptime du processus
    """

    return {
        "status": "OK",
        "version": settings.api_version,
        "uptime_seconds": int(time() - _process_start_time),
    }

