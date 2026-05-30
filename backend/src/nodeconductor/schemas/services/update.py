from typing import Literal

from pydantic import BaseModel, Field


class UpdateService(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=20)
    type: str | None = Field(default=None, min_length=2, max_length=20)
    category: str | None = Field(default=None, min_length=3, max_length=20)
    description: str | None = Field(default=None, min_length=3, max_length=200)
    status: Literal["on", "off", "error", "starting", "stopping"] | None = None
    dependencies: list[int] | None = None
    device_dependencies: list[int] | None = None
