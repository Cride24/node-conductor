"""Logique métier : dict brut → modèle API, tolérance, invariants."""

from pydantic import ValidationError

from nodeconductor.repositories.services_repository import (
    count_rows,
    fetch_row_by_id,
    fetch_rows_page,
)
from nodeconductor.schemas.services.common import Service
from nodeconductor.schemas.services.read import ServicesListResponse


class DataIntegrityError(Exception):
    """Donnée persistée incompatible avec le contrat API."""


def _build_service(row: dict) -> Service:
    try:
        return Service(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            category=row["category"],
            description=row["description"],
            status=row["status"],
            dependencies=row["dependencies"],
            device_dependencies=row["device_dependencies"],
        )
    except ValidationError as exc:
        sid = row.get("id", "unknown")
        raise DataIntegrityError(
            f"Invalid persisted data for service id={sid}: {exc.errors()}"
        ) from exc


def list_all_services_tolerant(limit: int = 50, offset: int = 0) -> ServicesListResponse:
    # Le listing reste disponible meme si une ligne persistee est invalide.
    rows = fetch_rows_page(limit, offset)
    valid_services: list[Service] = []
    warnings: list[str] = []

    for row in rows:
        try:
            valid_services.append(_build_service(row))
        except DataIntegrityError as exc:
            warnings.append(str(exc))

    total_count = count_rows()
    valid = len(valid_services)
    invalid = len(warnings)

    if len(rows) != valid + invalid:
        raise DataIntegrityError(
            "Invariant broken: page size != valid_count + invalid_count"
        )

    return ServicesListResponse(
        total=total_count,
        valid_count=valid,
        services=valid_services,
        invalid_count=invalid,
        warnings=warnings,
        limit=limit,
        offset=offset,
    )


def get_service_by_id(service_id: int) -> Service | None:
    row = fetch_row_by_id(service_id)
    if row is None:
        return None
    return _build_service(row)
