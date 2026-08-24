from dataclasses import dataclass
import time
from typing import Callable, Literal, Protocol
from uuid import UUID


WorkerMode = Literal["simulation", "real"]
WorkerResult = Literal["succeeded", "failed", "indeterminate"]


@dataclass(frozen=True)
class WorkerExecutionResult:
    """Resultat normalise renvoye par un executor worker."""

    status: WorkerResult
    error_message: str | None = None


class WorkerDeadlineExceededError(TimeoutError):
    """La deadline a expire avant une issue potentiellement ambigue."""


class WorkerExecutionIndeterminateError(RuntimeError):
    """Une operation a pu etre envoyee sans resultat final fiable."""


class WorkerExecutionFailedError(RuntimeError):
    """L'executor a confirme que l'operation a echoue."""


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Budget monotone et identite stable transmis a chaque executor interne."""

    operation_id: UUID
    deadline: float
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def for_timeout(
        cls,
        operation_id: UUID,
        timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> "WorkerExecutionContext":
        return cls(
            operation_id=operation_id,
            deadline=clock() + timeout_seconds,
            clock=clock,
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def is_expired(self) -> bool:
        return self.remaining_seconds() <= 0.0

    def raise_if_expired(self) -> None:
        if self.is_expired():
            raise WorkerDeadlineExceededError(
                "worker execution deadline expired"
            )


class WorkerExecutor(Protocol):
    """Contrat cooperatif pour une execution simulation ou reelle."""

    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
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

    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        context.raise_if_expired()
        return WorkerExecutionResult(self.result, self.error_message)


class RealWorkerExecutor:
    """Point d'extension futur pour Docker, Proxmox et Wake-on-LAN."""

    def execute(
        self,
        job: dict,
        context: WorkerExecutionContext,
    ) -> WorkerExecutionResult:
        context.raise_if_expired()
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
