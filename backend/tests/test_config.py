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
