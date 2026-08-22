import psycopg

from nodeconductor.core.config import settings
from nodeconductor.repositories.services_repository import _connect


def test_postgresql_connection_applies_timeouts(monkeypatch) -> None:
    captured: dict = {}
    connection = object()

    def fake_connect(database_url: str, **kwargs):
        captured["database_url"] = database_url
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    result = _connect()

    assert result is connection
    assert captured["database_url"] == settings.database_url
    assert captured["connect_timeout"] == settings.database_connect_timeout_seconds
    assert (
        f"statement_timeout={settings.database_statement_timeout_ms}"
        in captured["options"]
    )
    assert f"lock_timeout={settings.database_lock_timeout_ms}" in captured["options"]
