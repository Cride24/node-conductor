"""Schémas de réponse (lecture) pour les services."""

from pydantic import BaseModel, Field

from .common import Service


class ServicesListResponse(BaseModel):
    """Reponse de listing tolerant: les warnings gardent trace des lignes invalides."""

    total: int = Field(..., ge=0)
    valid_count: int = Field(..., ge=0)
    services: list[Service]
    invalid_count: int = Field(..., ge=0)
    warnings: list[str]
