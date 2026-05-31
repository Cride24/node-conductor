from nodeconductor.repositories.services_repository import (
    add_service,
    fetch_row_by_name,
)
from nodeconductor.schemas.services.common import Service
from nodeconductor.schemas.services.create import New_service
from nodeconductor.services.events import record_event


class ServiceAlreadyExistsError(ValueError):
    """Erreur métier levée quand un nom de service existe déjà."""


def create_service(service: New_service) -> Service:
    # L'unicite du nom est une regle metier exposee par l'API en 409 Conflict.
    if fetch_row_by_name(service.name) is not None:
        raise ServiceAlreadyExistsError(
            f"Service with name {service.name} already exists"
        )

    created_row = add_service(service.model_dump())
    record_event(
        event_type="service.created",
        severity="info",
        message=f"Service {created_row['name']} created",
        service_id=created_row["id"],
        actor_type="system",
        details={"name": created_row["name"]},
    )
    return Service(**created_row)
