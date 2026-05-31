from pydantic import BaseModel, ConfigDict, Field


class UpdateService(BaseModel):
    # Refuse notamment status: voir Docs/API-v1.md, section PATCH.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=20)
    type: str | None = Field(default=None, min_length=2, max_length=20)
    category: str | None = Field(default=None, min_length=3, max_length=20)
    description: str | None = Field(default=None, min_length=3, max_length=200)
    dependencies: list[int] | None = None
    device_dependencies: list[int] | None = None
