from fastapi import APIRouter, HTTPException, Path, Query, Response

from nodeconductor.schemas.services.common import Service
from nodeconductor.schemas.jobs.common import ServiceActionResponse
from nodeconductor.schemas.jobs.create import JobRequestContext
from nodeconductor.schemas.services.read import ServicesListResponse
from nodeconductor.schemas.services.create import New_service
from nodeconductor.schemas.services.update import UpdateService
from nodeconductor.services.listing import (
    DataIntegrityError,
    get_service_by_id,
    list_all_services_tolerant,
)
from nodeconductor.services.register import create_service
from nodeconductor.services.register import ServiceAlreadyExistsError
from nodeconductor.services.update import (
    EmptyServiceUpdateError,
    RequiredServiceFieldCannotBeNullError,
    ServiceNameAlreadyExistsError,
    update_service,
)
from nodeconductor.services.jobs import (
    ServiceActionConflictError,
    request_service_start,
    request_service_stop,
)


router = APIRouter()


@router.get("/api/v1/services", response_model=ServicesListResponse)
def list_services_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ServicesListResponse:
    return list_all_services_tolerant(limit, offset)


@router.get("/api/v1/services/{service_id}", response_model=Service)
def get_service_by_id_endpoint(service_id: int = Path(ge=1)) -> Service:
    try:
        service = get_service_by_id(service_id)
    except DataIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.post("/api/v1/services/", response_model=Service, status_code=201)
def create_service_endpoint(service: New_service) -> Service:
    try:
        return create_service(service)
    except ServiceAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/api/v1/services/{service_id}", response_model=Service)
def update_service_endpoint(
    service: UpdateService,
    service_id: int = Path(ge=1),
) -> Service:
    # Le PATCH general exclut volontairement status: voir Docs/API-v1.md.
    try:
        updated_service = update_service(service_id, service)
    except (EmptyServiceUpdateError, RequiredServiceFieldCannotBeNullError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceNameAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if updated_service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return updated_service


@router.post("/api/v1/services/{service_id}/start", response_model=ServiceActionResponse)
def start_service_endpoint(
    response: Response,
    context: JobRequestContext | None = None,
    service_id: int = Path(ge=1),
) -> ServiceActionResponse:
    try:
        action_response = request_service_start(
            service_id,
            context or JobRequestContext(),
        )
    except ServiceActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if action_response is None:
        raise HTTPException(status_code=404, detail="Service not found")
    # 202 signifie qu'un nouveau job est cree; 200 reste reserve a l'idempotence.
    if action_response.job_id is not None and action_response.message is None:
        response.status_code = 202
    return action_response


@router.post("/api/v1/services/{service_id}/stop", response_model=ServiceActionResponse)
def stop_service_endpoint(
    response: Response,
    context: JobRequestContext | None = None,
    service_id: int = Path(ge=1),
) -> ServiceActionResponse:
    try:
        action_response = request_service_stop(
            service_id,
            context or JobRequestContext(),
        )
    except ServiceActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if action_response is None:
        raise HTTPException(status_code=404, detail="Service not found")
    # Meme convention que start: 202 pour une nouvelle demande, 200 si deja traite.
    if action_response.job_id is not None and action_response.message is None:
        response.status_code = 202
    return action_response
