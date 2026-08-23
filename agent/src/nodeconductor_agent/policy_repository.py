"""Local SQLite policies and idempotent audit operations."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from nodeconductor_agent.errors import OperationConflictError
from nodeconductor_agent.models import (
    ManagementPolicy,
    PolicyUpdateResponse,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS container_policies (
    container_id TEXT PRIMARY KEY,
    current_name TEXT NOT NULL,
    management_policy TEXT NOT NULL DEFAULT 'discovered',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (management_policy IN ('discovered', 'managed', 'protected'))
);

CREATE TABLE IF NOT EXISTS policy_audit (
    operation_id TEXT PRIMARY KEY,
    container_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    previous_policy TEXT NOT NULL,
    management_policy TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (container_id) REFERENCES container_policies(container_id),
    CHECK (previous_policy IN ('discovered', 'managed', 'protected')),
    CHECK (management_policy IN ('discovered', 'managed', 'protected'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PolicyRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def observe(self, container_id: str, current_name: str) -> ManagementPolicy:
        observed_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO container_policies (
                    container_id,
                    current_name,
                    first_seen_at,
                    last_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (container_id) DO UPDATE SET
                    current_name = excluded.current_name,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    container_id,
                    current_name,
                    observed_at,
                    observed_at,
                    observed_at,
                ),
            )
            row = connection.execute(
                """
                SELECT management_policy
                FROM container_policies
                WHERE container_id = ?
                """,
                (container_id,),
            ).fetchone()
        return row["management_policy"]

    def set_policy(
        self,
        container_id: str,
        current_name: str,
        management_policy: ManagementPolicy,
        operation_id: str,
        actor: str,
    ) -> PolicyUpdateResponse:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch_operation(connection, operation_id)
            if existing is not None:
                self._validate_replay(
                    existing,
                    container_id,
                    management_policy,
                    actor,
                )
                return self._operation_response(existing)
            previous_policy = self._observe_in_transaction(
                connection,
                container_id,
                current_name,
            )
            changed_at = _now()
            connection.execute(
                """
                UPDATE container_policies
                SET management_policy = ?, updated_at = ?
                WHERE container_id = ?
                """,
                (management_policy, changed_at, container_id),
            )
            connection.execute(
                """
                INSERT INTO policy_audit (
                    operation_id,
                    container_id,
                    actor,
                    previous_policy,
                    management_policy,
                    changed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    container_id,
                    actor,
                    previous_policy,
                    management_policy,
                    changed_at,
                ),
            )
            row = self._fetch_operation(connection, operation_id)
        return self._operation_response(row)

    def replay_operation(
        self,
        operation_id: str,
        container_id: str,
        management_policy: ManagementPolicy,
        actor: str,
    ) -> PolicyUpdateResponse | None:
        with self._connection() as connection:
            row = self._fetch_operation(connection, operation_id)
        if row is None:
            return None
        self._validate_replay(
            row,
            container_id,
            management_policy,
            actor,
        )
        return self._operation_response(row)

    def list_audit_rows(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM policy_audit ORDER BY changed_at, operation_id"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _observe_in_transaction(
        connection: sqlite3.Connection,
        container_id: str,
        current_name: str,
    ) -> ManagementPolicy:
        observed_at = _now()
        connection.execute(
            """
            INSERT INTO container_policies (
                container_id,
                current_name,
                first_seen_at,
                last_seen_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (container_id) DO UPDATE SET
                current_name = excluded.current_name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                container_id,
                current_name,
                observed_at,
                observed_at,
                observed_at,
            ),
        )
        row = connection.execute(
            """
            SELECT management_policy
            FROM container_policies
            WHERE container_id = ?
            """,
            (container_id,),
        ).fetchone()
        return row["management_policy"]

    @staticmethod
    def _fetch_operation(
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM policy_audit WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()

    @staticmethod
    def _validate_replay(
        row: sqlite3.Row,
        container_id: str,
        management_policy: str,
        actor: str,
    ) -> None:
        if (
            row["container_id"] != container_id
            or row["management_policy"] != management_policy
            or row["actor"] != actor
        ):
            raise OperationConflictError()

    @staticmethod
    def _operation_response(row: sqlite3.Row) -> PolicyUpdateResponse:
        return PolicyUpdateResponse(
            operation_id=row["operation_id"],
            container_id=row["container_id"],
            actor=row["actor"],
            previous_policy=row["previous_policy"],
            management_policy=row["management_policy"],
            changed_at=row["changed_at"],
        )
