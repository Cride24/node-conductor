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


def _env_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _env_bounded_int(name: str, default: int, maximum: int) -> int:
    value = _env_positive_int(name, default)
    if value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
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
        self.api_max_request_body_bytes = _env_positive_int(
            "NODECONDUCTOR_API_MAX_REQUEST_BODY_BYTES",
            65_536,
        )
        self.api_request_timeout_seconds = _env_positive_int(
            "NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS",
            10,
        )
        self.database_connect_timeout_seconds = _env_positive_int(
            "NODECONDUCTOR_DATABASE_CONNECT_TIMEOUT_SECONDS",
            3,
        )
        self.database_statement_timeout_ms = _env_positive_int(
            "NODECONDUCTOR_DATABASE_STATEMENT_TIMEOUT_MS",
            5_000,
        )
        self.database_lock_timeout_ms = _env_positive_int(
            "NODECONDUCTOR_DATABASE_LOCK_TIMEOUT_MS",
            2_000,
        )
        self.worker_execution_timeout_seconds = _env_positive_int(
            "NODECONDUCTOR_WORKER_EXECUTION_TIMEOUT_SECONDS",
            30,
        )
        self.worker_max_concurrency = _env_positive_int(
            "NODECONDUCTOR_WORKER_MAX_CONCURRENCY",
            4,
        )
        self.worker_max_concurrency_per_connection = _env_positive_int(
            "NODECONDUCTOR_WORKER_MAX_CONCURRENCY_PER_CONNECTION",
            2,
        )
        self.agent_connect_timeout_seconds = _env_bounded_int(
            "NODECONDUCTOR_AGENT_CONNECT_TIMEOUT_SECONDS",
            2,
            30,
        )
        self.agent_response_timeout_seconds = _env_bounded_int(
            "NODECONDUCTOR_AGENT_RESPONSE_TIMEOUT_SECONDS",
            5,
            60,
        )
        self.agent_max_response_bytes = _env_bounded_int(
            "NODECONDUCTOR_AGENT_MAX_RESPONSE_BYTES",
            262_144,
            4_194_304,
        )
        self.agent_sync_page_size = _env_bounded_int(
            "NODECONDUCTOR_AGENT_SYNC_PAGE_SIZE",
            100,
            100,
        )
        self.agent_sync_max_pages = _env_bounded_int(
            "NODECONDUCTOR_AGENT_SYNC_MAX_PAGES",
            20,
            100,
        )

settings = Settings()
