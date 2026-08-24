"""Local SQLite policies keyed by typed operational resource identity."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from nodeconductor_agent.errors import OperationConflictError
from nodeconductor_agent.models import (
    ManagementPolicy,
    PolicyUpdateResponse,
    TargetKind,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_policies (
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    current_name TEXT NOT NULL,
    management_policy TEXT NOT NULL DEFAULT 'discovered',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (target_kind, target),
    CHECK (target_kind IN ('compose_project', 'standalone_container')),
    CHECK (management_policy IN ('discovered', 'managed', 'protected'))
);

CREATE TABLE IF NOT EXISTS resource_policy_audit (
    operation_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    actor TEXT NOT NULL,
    previous_policy TEXT NOT NULL,
    management_policy TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (target_kind, target)
        REFERENCES resource_policies(target_kind, target),
    CHECK (target_kind IN ('compose_project', 'standalone_container')),
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
            self._migrate_legacy_container_policies(connection)

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

    @staticmethod
    def _migrate_legacy_container_policies(connection: sqlite3.Connection) -> None:
        exists = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'container_policies'
            """
        ).fetchone()
        if exists is None:
            return
        connection.execute(
            """
            INSERT OR IGNORE INTO resource_policies (
                target_kind, target, current_name, management_policy,
                first_seen_at, last_seen_at, updated_at
            )
            SELECT
                'standalone_container', container_id, current_name,
                management_policy, first_seen_at, last_seen_at, updated_at
            FROM container_policies
            """
        )

    def observe(
        self,
        target_kind: TargetKind,
        target: str,
        current_name: str,
    ) -> ManagementPolicy:
        with self._connection() as connection:
            return self._observe_in_transaction(
                connection, target_kind, target, current_name
            )

    def force_protected(
        self,
        target_kind: TargetKind,
        target: str,
        current_name: str,
    ) -> None:
        with self._connection() as connection:
            self._observe_in_transaction(
                connection, target_kind, target, current_name
            )
            connection.execute(
                """
                UPDATE resource_policies
                SET management_policy = 'protected', updated_at = ?
                WHERE target_kind = ? AND target = ?
                """,
                (_now(), target_kind, target),
            )

    def set_policy(
        self,
        target_kind: TargetKind,
        target: str,
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
                    existing, target_kind, target, management_policy, actor
                )
                return self._operation_response(existing)
            previous_policy = self._observe_in_transaction(
                connection, target_kind, target, current_name
            )
            changed_at = _now()
            connection.execute(
                """
                UPDATE resource_policies
                SET management_policy = ?, updated_at = ?
                WHERE target_kind = ? AND target = ?
                """,
                (management_policy, changed_at, target_kind, target),
            )
            connection.execute(
                """
                INSERT INTO resource_policy_audit (
                    operation_id, target_kind, target, actor, previous_policy,
                    management_policy, changed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    target_kind,
                    target,
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
        target_kind: TargetKind,
        target: str,
        management_policy: ManagementPolicy,
        actor: str,
    ) -> PolicyUpdateResponse | None:
        with self._connection() as connection:
            row = self._fetch_operation(connection, operation_id)
        if row is None:
            return None
        self._validate_replay(
            row, target_kind, target, management_policy, actor
        )
        return self._operation_response(row)

    def list_audit_rows(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resource_policy_audit
                ORDER BY changed_at, operation_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _observe_in_transaction(
        connection: sqlite3.Connection,
        target_kind: TargetKind,
        target: str,
        current_name: str,
    ) -> ManagementPolicy:
        observed_at = _now()
        connection.execute(
            """
            INSERT INTO resource_policies (
                target_kind, target, current_name,
                first_seen_at, last_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (target_kind, target) DO UPDATE SET
                current_name = excluded.current_name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                target_kind,
                target,
                current_name,
                observed_at,
                observed_at,
                observed_at,
            ),
        )
        row = connection.execute(
            """
            SELECT management_policy
            FROM resource_policies
            WHERE target_kind = ? AND target = ?
            """,
            (target_kind, target),
        ).fetchone()
        return row["management_policy"]

    @staticmethod
    def _fetch_operation(
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM resource_policy_audit WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()

    @staticmethod
    def _validate_replay(
        row: sqlite3.Row,
        target_kind: str,
        target: str,
        management_policy: str,
        actor: str,
    ) -> None:
        if (
            row["target_kind"] != target_kind
            or row["target"] != target
            or row["management_policy"] != management_policy
            or row["actor"] != actor
        ):
            raise OperationConflictError()

    @staticmethod
    def _operation_response(row: sqlite3.Row) -> PolicyUpdateResponse:
        return PolicyUpdateResponse(
            operation_id=row["operation_id"],
            target_kind=row["target_kind"],
            target=row["target"],
            actor=row["actor"],
            previous_policy=row["previous_policy"],
            management_policy=row["management_policy"],
            changed_at=row["changed_at"],
        )
