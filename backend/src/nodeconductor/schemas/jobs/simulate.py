from typing import Literal

from pydantic import BaseModel, ConfigDict


class SimulateJobCompletionRequest(BaseModel):
    # Payload volontairement strict: la simulation doit rester previsible.
    model_config = ConfigDict(extra="forbid")

    result: Literal["succeeded", "failed"] = "succeeded"
    error_message: str | None = None
