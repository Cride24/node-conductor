"""Synchronisation atomique de l'inventaire Agent dans PostgreSQL."""

from datetime import datetime

from nodeconductor.repositories.services_repository import (
    _connect,
    ensure_agent_sync_schema,
)


TARGET_COLUMNS = """
    id,
    driver,
    connection_id,
    target,
    management_policy,
    display_name,
    observed_state,
    observed_health_status,
    last_seen_at,
    is_present
"""


class AgentConnectionNotFoundError(Exception):
    pass


def synchronize_inventory_rows(
    connection_id: str,
    containers: list[dict],
    observed_at: datetime,
) -> dict:
    ensure_agent_sync_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            _lock_connection(cursor, connection_id)
            existing = _existing_targets(cursor, connection_id)
            synchronized = [
                _upsert_container(cursor, connection_id, item, observed_at)
                for item in containers
            ]
            observed_ids = [item["id"] for item in containers]
            absent_count = _mark_absent(cursor, connection_id, observed_ids)
    discovered = [
        row for row in synchronized if row["target"] not in existing
    ]
    return {
        "discovered": discovered,
        "created_count": len(discovered),
        "updated_count": len(synchronized) - len(discovered),
        "absent_count": absent_count,
        "total_count": len(synchronized),
    }


def fetch_inventory_target_rows(connection_id: str) -> list[dict]:
    ensure_agent_sync_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {TARGET_COLUMNS}
                FROM targets
                WHERE driver = 'docker' AND connection_id = %s
                ORDER BY target
                """,
                (connection_id,),
            )
            return list(cursor.fetchall())


def _lock_connection(cursor, connection_id: str) -> None:
    cursor.execute(
        "SELECT id FROM agent_connections WHERE id = %s FOR UPDATE",
        (connection_id,),
    )
    if cursor.fetchone() is None:
        raise AgentConnectionNotFoundError(connection_id)


def _existing_targets(cursor, connection_id: str) -> set[str]:
    cursor.execute(
        """
        SELECT target
        FROM targets
        WHERE driver = 'docker' AND connection_id = %s
        """,
        (connection_id,),
    )
    return {row["target"] for row in cursor.fetchall()}


def _upsert_container(
    cursor,
    connection_id: str,
    container: dict,
    observed_at: datetime,
) -> dict:
    cursor.execute(
        f"""
        INSERT INTO targets (
            driver,
            connection_id,
            target,
            management_policy,
            display_name,
            observed_state,
            observed_health_status,
            last_seen_at,
            is_present
        )
        VALUES (
            'docker',
            %(connection_id)s,
            %(id)s,
            %(management_policy)s,
            %(name)s,
            %(state)s,
            %(health_status)s,
            %(observed_at)s,
            TRUE
        )
        ON CONFLICT (driver, connection_id, target) DO UPDATE SET
            management_policy = EXCLUDED.management_policy,
            display_name = EXCLUDED.display_name,
            observed_state = EXCLUDED.observed_state,
            observed_health_status = EXCLUDED.observed_health_status,
            last_seen_at = EXCLUDED.last_seen_at,
            is_present = TRUE
        RETURNING {TARGET_COLUMNS}
        """,
        {
            **container,
            "connection_id": connection_id,
            "observed_at": observed_at,
        },
    )
    return cursor.fetchone()


def _mark_absent(cursor, connection_id: str, observed_ids: list[str]) -> int:
    cursor.execute(
        """
        UPDATE targets
        SET is_present = FALSE
        WHERE driver = 'docker'
            AND connection_id = %s
            AND is_present = TRUE
            AND NOT (target = ANY(%s))
        """,
        (connection_id, observed_ids),
    )
    return cursor.rowcount
