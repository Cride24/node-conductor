from pydantic import BaseModel, Field, ValidationError
from .common import Service, SERVICES_DATA


class ServicesListResponse(BaseModel):
    total: int = Field(..., ge=0)
    valid_count: int = Field(..., ge=0)
    services: list[Service]
    invalid_count: int = Field(..., ge=0)
    warnings: list[str]


class DataIntegrityError(Exception):
    """Raised when persisted data cannot be mapped to API model."""


def _build_service(service: dict) -> Service:
    try:
        return Service(
            id=service["id"],
            name=service["name"],
            type=service["type"],
            category=service["category"],
            description=service["description"],
            status=service["status"],
            dependencies=service["dependencies"],
            device_dependencies=service["device_dependencies"],
        )
    except ValidationError as exc:
        service_id = service.get("id", "unknown")
        raise DataIntegrityError(
            f"Invalid persisted data for service id={service_id}: {exc.errors()}"
        ) from exc


def list_all_services_tolerant():
    valid_services = []
    warnings = []
    for service in SERVICES_DATA:
        try:
            valid_services.append(_build_service(service))
        except DataIntegrityError as exc:
            warnings.append(str(exc))

    total_count = len(SERVICES_DATA)
    valid = len(valid_services)
    invalid = len(warnings)

    if total_count != valid + invalid:
        raise DataIntegrityError(
            "Invariant broken: total != valid_count + invalid_count"
        )
    return ServicesListResponse(
        total=total_count,
        valid_count=valid,
        services=valid_services,
        invalid_count=invalid,
        warnings=warnings,
    )


def get_service_by_id(service_id):
    for service in SERVICES_DATA:
        if service["id"] == service_id:
            return _build_service(service)
    return None
