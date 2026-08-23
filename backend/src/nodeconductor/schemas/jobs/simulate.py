from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SimulateJobCompletionRequest(BaseModel):
    # Payload volontairement strict: la simulation doit rester previsible.
    model_config = ConfigDict(extra="forbid")

    result: Literal["succeeded", "failed", "indeterminate"] = "succeeded"
    error_message: str | None = Field(default=None, max_length=2_000)
