from fastapi import APIRouter, HTTPException

from nodeconductor.services.listing import list_services, get_service_by_id

router = APIRouter()

@router.get("/api/v1/services")
def list_services_endpoint():
    return list_services()

@router.get("/api/v1/services/{service_id}")
def get_service_by_id_endpoint(service_id: int):
    service = get_service_by_id(service_id)
    if service:
        return service
    else:
        raise HTTPException(status_code=404, detail="Service not found")