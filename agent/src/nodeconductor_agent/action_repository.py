"""Crash-safe, idempotent SQLite journal for restricted Agent actions."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from nodeconductor_agent.errors import OperationConflictError
from nodeconductor_agent.models import (
    ActionResourceState,
    ActionStatus,
    ResourceAction,
    ResourceActionResponse,
    TargetKind,
)


ACTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_action_operations (
    operation_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    result_code TEXT,
    result_message TEXT,
    dispatched INTEGER NOT NULL DEFAULT 0,
    resource_state TEXT,
    resource_health_status TEXT,
    resource_management_policy TEXT,
    resource_is_pilotable INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    CHECK (target_kind IN ('compose_project', 'standalone_container')),
    CHECK (action IN ('start', 'stop')),
    CHECK (status IN (
        'in_progress', 'completed', 'rejected', 'failed', 'indeterminate'
    )),
    CHECK (dispatched IN (0, 1)),
    CHECK (resource_is_pilotable IS NULL OR resource_is_pilotable IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_action_per_resource
ON resource_action_operations(target_kind, target)
WHERE status = 'in_progress';
"""


@dataclass(frozen=True)
class ActionBeginResult:
    kind: str
    response: ResourceActionResponse | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(ACTION_SCHEMA)
            recovered_at = _now()
            connection.execute(
                """
                UPDATE resource_action_operations
                SET status = 'indeterminate',
                    result_code = 'recovered_incomplete_operation',
                    result_message = 'Operation outcome is unknown after Agent restart',
                    finished_at = ?
                WHERE status = 'in_progress'
                """,
                (recovered_at,),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def begin(
        self,
        operation_id: str,
        target_kind: TargetKind,
        target: str,
        actor: str,
        action: ResourceAction,
    ) -> ActionBeginResult:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, operation_id)
            if existing is not None:
                self._validate_replay(existing, target_kind, target, actor, action)
                if existing["status"] == "in_progress":
                    return ActionBeginResult("in_progress")
                return ActionBeginResult("replay", self._response(existing))
            active = connection.execute(
                """
                SELECT operation_id
                FROM resource_action_operations
                WHERE target_kind = ? AND target = ? AND status = 'in_progress'
                """,
                (target_kind, target),
            ).fetchone()
            started_at = _now()
            if active is not None:
                connection.execute(
                    """
                    INSERT INTO resource_action_operations (
                        operation_id, target_kind, target, actor, action, status,
                        result_code, result_message, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, 'rejected', ?, ?, ?, ?)
                    """,
                    (
                        operation_id,
                        target_kind,
                        target,
                        actor,
                        action,
                        "resource_busy",
                        "Another action is active for this resource",
                        started_at,
                        started_at,
                    ),
                )
                row = self._fetch(connection, operation_id)
                return ActionBeginResult("busy", self._response(row))
            connection.execute(
                """
                INSERT INTO resource_action_operations (
                    operation_id, target_kind, target, actor, action,
                    status, started_at
                ) VALUES (?, ?, ?, ?, ?, 'in_progress', ?)
                """,
                (operation_id, target_kind, target, actor, action, started_at),
            )
        return ActionBeginResult("started")

    def mark_dispatched(self, operation_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE resource_action_operations
                SET dispatched = 1
                WHERE operation_id = ? AND status = 'in_progress'
                """,
                (operation_id,),
            )

    def finish(
        self,
        operation_id: str,
        status: ActionStatus,
        result_code: str,
        message: str,
        resource: ActionResourceState | None = None,
    ) -> ResourceActionResponse:
        finished_at = _now()
        state_values = (
            (None, None, None, None)
            if resource is None
            else (
                resource.state,
                resource.health_status,
                resource.management_policy,
                int(resource.is_pilotable),
            )
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE resource_action_operations
                SET status = ?, result_code = ?, result_message = ?,
                    resource_state = ?, resource_health_status = ?,
                    resource_management_policy = ?, resource_is_pilotable = ?,
                    finished_at = ?
                WHERE operation_id = ? AND status = 'in_progress'
                """,
                (
                    status,
                    result_code,
                    message,
                    *state_values,
                    finished_at,
                    operation_id,
                ),
            )
            row = self._fetch(connection, operation_id)
        return self._response(row)

    def replay(
        self,
        operation_id: str,
        target_kind: TargetKind,
        target: str,
        actor: str,
        action: ResourceAction,
    ) -> ResourceActionResponse | None:
        with self._connection() as connection:
            row = self._fetch(connection, operation_id)
        if row is None or row["status"] == "in_progress":
            return None
        self._validate_replay(row, target_kind, target, actor, action)
        return self._response(row)

    def list_rows(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM resource_action_operations ORDER BY started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _fetch(
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM resource_action_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()

    @staticmethod
    def _validate_replay(
        row: sqlite3.Row,
        target_kind: TargetKind,
        target: str,
        actor: str,
        action: ResourceAction,
    ) -> None:
        if (
            row["target_kind"] != target_kind
            or row["target"] != target
            or row["actor"] != actor
            or row["action"] != action
        ):
            raise OperationConflictError()

    @staticmethod
    def _response(row: sqlite3.Row) -> ResourceActionResponse:
        resource = None
        if row["resource_state"] is not None:
            resource = ActionResourceState(
                target_kind=row["target_kind"],
                target=row["target"],
                state=row["resource_state"],
                health_status=row["resource_health_status"],
                management_policy=row["resource_management_policy"],
                is_pilotable=bool(row["resource_is_pilotable"]),
            )
        return ResourceActionResponse(
            operation_id=row["operation_id"],
            actor=row["actor"],
            action=row["action"],
            target_kind=row["target_kind"],
            target=row["target"],
            status=row["status"],
            result_code=row["result_code"],
            message=row["result_message"],
            resource=resource,
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
