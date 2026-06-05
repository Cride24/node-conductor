import os


VALID_WORKER_MODES = {"simulation", "real"}
VALID_EVENT_LEVELS = {"info", "debug"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, default: str, valid_values: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in valid_values:
        valid_list = ", ".join(sorted(valid_values))
        raise ValueError(f"{name} must be one of: {valid_list}")
    return value


class Settings:
    """
    Settings minimalistes pour le MVP.

    On commence simple : si l'on doit étendre (DB, auth, etc.), on remodularisera.
    """

    def __init__(self) -> None:
        self.name = os.getenv("NODECONDUCTOR_NAME", "NodeConductor")
        self.version = os.getenv("NODECONDUCTOR_VERSION", "0.1.0")
        self.api_version = os.getenv("NODECONDUCTOR_API_VERSION", "0.1.1")
        self.database_url = os.getenv(
            "NODECONDUCTOR_DATABASE_URL",
            "postgresql://nodeconductor:nodeconductor_dev@localhost:5432/nodeconductor",
        )
        self.worker_auto_enabled = _env_bool("NODECONDUCTOR_WORKER_AUTO_ENABLED", False)
        self.worker_poll_interval_seconds = max(
            1.0,
            float(os.getenv("NODECONDUCTOR_WORKER_POLL_INTERVAL_SECONDS", "5")),
        )
        self.worker_mode = _env_choice(
            "NODECONDUCTOR_WORKER_MODE",
            "simulation",
            VALID_WORKER_MODES,
        )
        self.event_level = _env_choice(
            "NODECONDUCTOR_EVENT_LEVEL",
            "info",
            VALID_EVENT_LEVELS,
        )

settings = Settings()
