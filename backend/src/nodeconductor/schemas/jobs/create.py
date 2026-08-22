from pydantic import BaseModel, ConfigDict, Field

from nodeconductor.schemas.jobs.common import RequestedByType


class JobRequestContext(BaseModel):
    # Le demandeur est trace pour audit, surtout quand la source est un LLM.
    model_config = ConfigDict(extra="forbid")

    requested_by_type: RequestedByType = "unknown"
    requested_by_id: str | None = Field(default=None, max_length=100)
