from pydantic import BaseModel, Field


class New_service(BaseModel):
    """Payload de creation: status est laisse au defaut PostgreSQL."""

    name: str = Field(..., min_length=3, max_length=20)
    type: str = Field(..., min_length=2, max_length=20)  # ex. LXC, VM
    category: str = Field(..., min_length=3, max_length=20)  # ex. game, tool
    description: str = Field(..., min_length=3, max_length=200)
    dependencies: list[int] | None = None  # ids de services requis
    device_dependencies: list[int] | None = None  # ids d'equipements requis
