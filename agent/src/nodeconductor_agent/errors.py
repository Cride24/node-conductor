"""Safe domain errors returned by the restricted Agent API."""


class AgentError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class EngineUnavailableError(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "engine_unavailable",
            "Docker Engine is unavailable",
            503,
        )


class ContainerNotFoundError(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "container_not_found",
            "Docker container was not found",
            404,
        )


class DockerOperationError(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "docker_operation_failed",
            "Docker inventory operation failed",
            502,
        )


class OperationConflictError(AgentError):
    def __init__(self) -> None:
        super().__init__(
            "operation_id_conflict",
            "operation_id was already used for another policy request",
            409,
        )
