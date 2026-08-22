from pydantic import BaseModel, ConfigDict, Field

from nodeconductor.schemas.services.common import DependencyId


class New_service(BaseModel):
    """Payload de creation: status est laisse au defaut PostgreSQL."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=3, max_length=20)
    type: str = Field(..., min_length=2, max_length=20)  # ex. LXC, VM
    category: str = Field(..., min_length=3, max_length=20)  # ex. game, tool
    description: str = Field(..., min_length=3, max_length=200)
    dependencies: list[DependencyId] | None = Field(default=None, max_length=50)
    device_dependencies: list[DependencyId] | None = Field(
        default=None,
        max_length=50,
    )
