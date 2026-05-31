from nodeconductor.repositories.services_repository import (
    add_service,
    fetch_row_by_name,
)
from nodeconductor.schemas.services.common import Service
from nodeconductor.schemas.services.create import New_service


class ServiceAlreadyExistsError(ValueError):
    """Erreur métier levée quand un nom de service existe déjà."""


def create_service(service: New_service) -> Service:
    # L'unicite du nom est une regle metier exposee par l'API en 409 Conflict.
    if fetch_row_by_name(service.name) is not None:
        raise ServiceAlreadyExistsError(
            f"Service with name {service.name} already exists"
        )

    created_row = add_service(service.model_dump())
    return Service(**created_row)
