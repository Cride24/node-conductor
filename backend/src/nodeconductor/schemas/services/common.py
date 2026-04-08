from pydantic import BaseModel, Field, ValidationError
from typing import Literal

class Service(BaseModel):
    id: int = Field(..., ge=0)
    name: str = Field(..., min_length=3, max_length=20)
    type: str = Field(..., min_length=3, max_length=20) # container type: LXC, VM, etc.
    category: str = Field(..., min_length=3, max_length=20) # service category: game, tool, etc.
    description: str = Field(..., min_length=3, max_length=200)
    status: Literal["on", "off", "error", "starting", "stopping"] = "off"
    dependencies: list[int] | None = None # list of service ids that this service depends on
    device_dependencies: list[int] | None = None # list of device ids that this service depends on

SERVICES_DATA = [
    {
        "id": 1,
        "name": "steampunk",
        "type": "LXC",
        "category": "game",
        "description": "serveur minecraft sur le thème steampunk",
        "status": "off"
    },
    {
        "id": 2,
        "name": "stefano",
        "type": "VM",
        "category": "tool",
        "description": "outil de développement pour le projet stefano",
        "status": "on"
    }
]