from nodeconductor.repositories.services_repository import (
    fetch_row_by_name,
    update_service_row,
)
from nodeconductor.schemas.services.common import Service
from nodeconductor.schemas.services.update import UpdateService


class EmptyServiceUpdateError(ValueError):
    """Erreur metier levee quand aucun champ n'est fourni."""


class ServiceNameAlreadyExistsError(ValueError):
    """Erreur metier levee quand le nouveau nom est deja utilise."""


class RequiredServiceFieldCannotBeNullError(ValueError):
    """Erreur metier levee quand un champ obligatoire vaut null."""


def update_service(service_id: int, service: UpdateService) -> Service | None:
    updates = service.model_dump(exclude_unset=True)
    required_fields = {"name", "type", "category", "description"}
    null_required_fields = [
        field
        for field in required_fields
        if field in updates and updates[field] is None
    ]
    if null_required_fields:
        raise RequiredServiceFieldCannotBeNullError(
            f"Fields cannot be null: {sorted(null_required_fields)}"
        )
    if not updates:
        raise EmptyServiceUpdateError("At least one field must be provided")

    new_name = updates.get("name")
    if new_name is not None:
        existing_row = fetch_row_by_name(new_name)
        if existing_row is not None and existing_row["id"] != service_id:
            raise ServiceNameAlreadyExistsError(
                f"Service with name {new_name} already exists"
            )

    updated_row = update_service_row(service_id, updates)
    if updated_row is None:
        return None
    return Service(**updated_row)
