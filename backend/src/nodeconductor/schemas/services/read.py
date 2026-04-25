"""Schémas de réponse (lecture) pour les services."""

from pydantic import BaseModel, Field

from .common import Service


class ServicesListResponse(BaseModel):
    total: int = Field(..., ge=0)
    valid_count: int = Field(..., ge=0)
    services: list[Service]
    invalid_count: int = Field(..., ge=0)
    warnings: list[str]
