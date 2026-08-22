"""Contrats Pydantic partagés (forme des données API)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


DependencyId = Annotated[int, Field(ge=1)]


class Service(BaseModel):
    """Representation publique d'un service exposee par l'API."""

    id: int = Field(..., ge=0)
    name: str = Field(..., min_length=3, max_length=20)
    type: str = Field(..., min_length=2, max_length=20)  # ex. LXC, VM
    category: str = Field(..., min_length=3, max_length=20)  # ex. game, tool
    description: str = Field(..., min_length=3, max_length=200)
    # status reflete l'etat reel ou simule; il n'est pas modifiable par PATCH.
    status: Literal["on", "off", "error", "starting", "stopping"] = "off"
    dependencies: list[DependencyId] | None = Field(default=None, max_length=50)
    device_dependencies: list[DependencyId] | None = Field(
        default=None,
        max_length=50,
    )
