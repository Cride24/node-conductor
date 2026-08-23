import pytest

from nodeconductor.core.config import Settings


def test_worker_mode_defaults_to_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NODECONDUCTOR_WORKER_MODE", raising=False)
    monkeypatch.delenv("NODECONDUCTOR_EVENT_LEVEL", raising=False)

    settings = Settings()

    assert settings.worker_mode == "simulation"
    assert settings.event_level == "info"


def test_invalid_worker_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODECONDUCTOR_WORKER_MODE", "unsafe")

    with pytest.raises(ValueError, match="NODECONDUCTOR_WORKER_MODE"):
        Settings()


def test_invalid_event_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODECONDUCTOR_EVENT_LEVEL", "verbose")

    with pytest.raises(ValueError, match="NODECONDUCTOR_EVENT_LEVEL"):
        Settings()


def test_guardrail_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    variable_names = (
        "NODECONDUCTOR_API_MAX_REQUEST_BODY_BYTES",
        "NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS",
        "NODECONDUCTOR_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "NODECONDUCTOR_DATABASE_STATEMENT_TIMEOUT_MS",
        "NODECONDUCTOR_DATABASE_LOCK_TIMEOUT_MS",
        "NODECONDUCTOR_WORKER_EXECUTION_TIMEOUT_SECONDS",
        "NODECONDUCTOR_WORKER_MAX_CONCURRENCY",
        "NODECONDUCTOR_WORKER_MAX_CONCURRENCY_PER_CONNECTION",
        "NODECONDUCTOR_AGENT_CONNECT_TIMEOUT_SECONDS",
        "NODECONDUCTOR_AGENT_RESPONSE_TIMEOUT_SECONDS",
        "NODECONDUCTOR_AGENT_MAX_RESPONSE_BYTES",
        "NODECONDUCTOR_AGENT_SYNC_PAGE_SIZE",
        "NODECONDUCTOR_AGENT_SYNC_MAX_PAGES",
    )
    for variable_name in variable_names:
        monkeypatch.delenv(variable_name, raising=False)

    configured = Settings()

    assert configured.api_max_request_body_bytes == 65_536
    assert configured.api_request_timeout_seconds == 10
    assert configured.database_connect_timeout_seconds == 3
    assert configured.database_statement_timeout_ms == 5_000
    assert configured.database_lock_timeout_ms == 2_000
    assert configured.worker_execution_timeout_seconds == 30
    assert configured.worker_max_concurrency == 4
    assert configured.worker_max_concurrency_per_connection == 2
    assert configured.agent_connect_timeout_seconds == 2
    assert configured.agent_response_timeout_seconds == 5
    assert configured.agent_max_response_bytes == 262_144
    assert configured.agent_sync_page_size == 100
    assert configured.agent_sync_max_pages == 20


def test_worker_concurrency_limits_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODECONDUCTOR_WORKER_MAX_CONCURRENCY", "8")
    monkeypatch.setenv(
        "NODECONDUCTOR_WORKER_MAX_CONCURRENCY_PER_CONNECTION",
        "3",
    )

    configured = Settings()

    assert configured.worker_max_concurrency == 8
    assert configured.worker_max_concurrency_per_connection == 3


def test_non_positive_guardrail_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS", "0")

    with pytest.raises(
        ValueError,
        match="NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS",
    ):
        Settings()


def test_agent_pagination_limit_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODECONDUCTOR_AGENT_SYNC_PAGE_SIZE", "101")

    with pytest.raises(ValueError, match="must be at most 100"):
        Settings()
