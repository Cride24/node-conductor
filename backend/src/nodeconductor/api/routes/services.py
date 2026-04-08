from fastapi import APIRouter, HTTPException

from nodeconductor.services.listing import (
    DataIntegrityError,
    get_service_by_id,
    list_all_services_tolerant,
    ServicesListResponse,
)

router = APIRouter()

@router.get("/api/v1/services", response_model=ServicesListResponse)
def list_services_endpoint():
    return list_all_services_tolerant()

@router.get("/api/v1/services/{service_id}")
def get_service_by_id_endpoint(service_id: int):
    try:
        service = get_service_by_id(service_id)
    except DataIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if service:
        return service
    else:
        raise HTTPException(status_code=404, detail="Service not found")