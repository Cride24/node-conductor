from pydantic import BaseModel, ConfigDict

from nodeconductor.schemas.jobs.common import RequestedByType


class JobRequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by_type: RequestedByType = "unknown"
    requested_by_id: str | None = None
