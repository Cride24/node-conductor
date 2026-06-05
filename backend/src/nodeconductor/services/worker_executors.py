from dataclasses import dataclass
from typing import Literal, Protocol


WorkerMode = Literal["simulation", "real"]
WorkerResult = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class WorkerExecutionResult:
    """Resultat normalise renvoye par un executor worker."""

    status: WorkerResult
    error_message: str | None = None


class WorkerExecutor(Protocol):
    """Contrat minimal pour une execution simulation ou reelle."""

    def execute(self, job: dict) -> WorkerExecutionResult:
        ...


class SimulationWorkerExecutor:
    """Executor sur: aucune action reseau ou infrastructure reelle."""

    def __init__(
        self,
        result: WorkerResult = "succeeded",
        error_message: str | None = None,
    ) -> None:
        self.result = result
        self.error_message = error_message

    def execute(self, job: dict) -> WorkerExecutionResult:
        return WorkerExecutionResult(self.result, self.error_message)


class RealWorkerExecutor:
    """Point d'extension futur pour Docker, Proxmox et Wake-on-LAN."""

    def execute(self, job: dict) -> WorkerExecutionResult:
        return WorkerExecutionResult(
            "failed",
            "real worker mode is not implemented yet",
        )


def build_worker_executor(worker_mode: WorkerMode) -> WorkerExecutor:
    if worker_mode == "simulation":
        return SimulationWorkerExecutor()
    if worker_mode == "real":
        return RealWorkerExecutor()
    raise ValueError(f"Unsupported worker mode: {worker_mode}")
