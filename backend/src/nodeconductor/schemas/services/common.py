"""Contrats Pydantic partagés (forme des données API)."""

from typing import Literal

from pydantic import BaseModel, Field


class Service(BaseModel):
    id: int = Field(..., ge=0)
    name: str = Field(..., min_length=3, max_length=20)
    type: str = Field(..., min_length=2, max_length=20)  # ex. LXC, VM
    category: str = Field(..., min_length=3, max_length=20)  # ex. game, tool
    description: str = Field(..., min_length=3, max_length=200)
    status: Literal["on", "off", "error", "starting", "stopping"] = "off"
    dependencies: list[int] | None = None # list of service ids that this service depends on
    device_dependencies: list[int] | None = None # list of device ids that this service depends on
