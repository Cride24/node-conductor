"""Atomic synchronization of typed Docker resources into PostgreSQL."""

from datetime import datetime

from nodeconductor.repositories.services_repository import (
    _connect,
    ensure_agent_sync_schema,
)


TARGET_COLUMNS = """
    id,
    driver,
    connection_id,
    target_kind,
    target,
    management_policy,
    display_name,
    observed_state,
    observed_health_status,
    last_seen_at,
    is_present,
    is_pilotable,
    protection_forced
"""

MEMBER_COLUMNS = """
    id,
    connection_id,
    project_target_id,
    docker_id,
    display_name,
    compose_service,
    observed_state,
    observed_health_status,
    last_seen_at,
    is_present
"""


class AgentConnectionNotFoundError(Exception):
    pass


def synchronize_inventory_rows(
    connection_id: str,
    resources: list[dict],
    observed_at: datetime,
) -> dict:
    """Apply only a complete, validated Agent snapshot in one transaction."""
    ensure_agent_sync_schema()
    operational = [
        item for item in resources if item["classification"] == "operational"
    ]
    issues = [
        item for item in resources if item["classification"] == "ambiguous"
    ]
    with _connect() as conn:
        with conn.cursor() as cursor:
            _lock_connection(cursor, connection_id)
            existing = _existing_targets(cursor, connection_id)
            synchronized = [
                _upsert_resource(cursor, connection_id, item, observed_at)
                for item in operational
            ]
            target_ids = [row["id"] for row in synchronized]
            member_ids: list[int] = []
            member_docker_ids: list[str] = []
            for resource, target_row in zip(operational, synchronized):
                for member in resource["members"]:
                    row = _upsert_member(
                        cursor,
                        connection_id,
                        target_row["id"],
                        member,
                        observed_at,
                    )
                    member_ids.append(row["id"])
                    member_docker_ids.append(member["docker_id"])
            issue_ids = [
                _upsert_issue(cursor, connection_id, issue, observed_at)["id"]
                for issue in issues
            ]
            _disable_legacy_member_targets(
                cursor, connection_id, member_docker_ids
            )
            absent_count = _mark_targets_absent(
                cursor, connection_id, target_ids
            )
            member_absent_count = _mark_rows_absent(
                cursor,
                "compose_members",
                connection_id,
                member_ids,
            )
            issue_absent_count = _mark_rows_absent(
                cursor,
                "docker_inventory_issues",
                connection_id,
                issue_ids,
            )
    discovered = [
        row
        for row in synchronized
        if (row["target_kind"], row["target"]) not in existing
    ]
    return {
        "discovered": discovered,
        "created_count": len(discovered),
        "updated_count": len(synchronized) - len(discovered),
        "absent_count": absent_count,
        "member_count": len(member_ids),
        "member_absent_count": member_absent_count,
        "issue_count": len(issue_ids),
        "issue_absent_count": issue_absent_count,
        "total_count": len(resources),
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
                ORDER BY target_kind, target
                """,
                (connection_id,),
            )
            return list(cursor.fetchall())


def fetch_compose_member_rows(connection_id: str) -> list[dict]:
    ensure_agent_sync_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {MEMBER_COLUMNS}
                FROM compose_members
                WHERE connection_id = %s
                ORDER BY docker_id
                """,
                (connection_id,),
            )
            return list(cursor.fetchall())


def fetch_inventory_issue_rows(connection_id: str) -> list[dict]:
    ensure_agent_sync_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id, connection_id, docker_id, display_name,
                    observed_state, observed_health_status,
                    diagnostic_status, last_seen_at, is_present
                FROM docker_inventory_issues
                WHERE connection_id = %s
                ORDER BY docker_id
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


def _existing_targets(cursor, connection_id: str) -> set[tuple[str, str]]:
    cursor.execute(
        """
        SELECT target_kind, target
        FROM targets
        WHERE driver = 'docker' AND connection_id = %s
        """,
        (connection_id,),
    )
    return {
        (row["target_kind"], row["target"]) for row in cursor.fetchall()
    }


def _upsert_resource(
    cursor,
    connection_id: str,
    resource: dict,
    observed_at: datetime,
) -> dict:
    cursor.execute(
        f"""
        INSERT INTO targets (
            driver, connection_id, target_kind, target, management_policy,
            display_name, observed_state, observed_health_status,
            last_seen_at, is_present, is_pilotable, protection_forced
        )
        VALUES (
            'docker', %(connection_id)s, %(target_kind)s, %(target)s,
            %(management_policy)s, %(display_name)s, %(state)s,
            %(health_status)s, %(observed_at)s, TRUE, TRUE,
            %(protection_forced)s
        )
        ON CONFLICT (driver, connection_id, target_kind, target) DO UPDATE SET
            management_policy = CASE
                WHEN targets.protection_forced THEN 'protected'
                ELSE EXCLUDED.management_policy
            END,
            display_name = EXCLUDED.display_name,
            observed_state = EXCLUDED.observed_state,
            observed_health_status = EXCLUDED.observed_health_status,
            last_seen_at = EXCLUDED.last_seen_at,
            is_present = TRUE,
            is_pilotable = TRUE,
            protection_forced = (
                targets.protection_forced OR EXCLUDED.protection_forced
            )
        RETURNING {TARGET_COLUMNS}
        """,
        {
            **resource,
            "connection_id": connection_id,
            "observed_at": observed_at,
        },
    )
    return cursor.fetchone()


def _upsert_member(
    cursor,
    connection_id: str,
    project_target_id: int,
    member: dict,
    observed_at: datetime,
) -> dict:
    cursor.execute(
        f"""
        INSERT INTO compose_members (
            connection_id, project_target_id, docker_id, display_name,
            compose_service, observed_state, observed_health_status,
            last_seen_at, is_present
        )
        VALUES (
            %(connection_id)s, %(project_target_id)s, %(docker_id)s,
            %(name)s, %(compose_service)s, %(state)s, %(health_status)s,
            %(observed_at)s, TRUE
        )
        ON CONFLICT (connection_id, docker_id) DO UPDATE SET
            project_target_id = EXCLUDED.project_target_id,
            display_name = EXCLUDED.display_name,
            compose_service = EXCLUDED.compose_service,
            observed_state = EXCLUDED.observed_state,
            observed_health_status = EXCLUDED.observed_health_status,
            last_seen_at = EXCLUDED.last_seen_at,
            is_present = TRUE
        RETURNING {MEMBER_COLUMNS}
        """,
        {
            **member,
            "connection_id": connection_id,
            "project_target_id": project_target_id,
            "observed_at": observed_at,
        },
    )
    return cursor.fetchone()


def _upsert_issue(
    cursor,
    connection_id: str,
    issue: dict,
    observed_at: datetime,
) -> dict:
    cursor.execute(
        """
        INSERT INTO docker_inventory_issues (
            connection_id, docker_id, display_name, observed_state,
            observed_health_status, diagnostic_status, last_seen_at, is_present
        )
        VALUES (
            %(connection_id)s, %(target)s, %(display_name)s, %(state)s,
            %(health_status)s, %(diagnostic_status)s, %(observed_at)s, TRUE
        )
        ON CONFLICT (connection_id, docker_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            observed_state = EXCLUDED.observed_state,
            observed_health_status = EXCLUDED.observed_health_status,
            diagnostic_status = EXCLUDED.diagnostic_status,
            last_seen_at = EXCLUDED.last_seen_at,
            is_present = TRUE
        RETURNING id
        """,
        {
            **issue,
            "connection_id": connection_id,
            "observed_at": observed_at,
        },
    )
    return cursor.fetchone()


def _disable_legacy_member_targets(
    cursor,
    connection_id: str,
    member_docker_ids: list[str],
) -> None:
    cursor.execute(
        """
        UPDATE targets
        SET is_pilotable = FALSE, is_present = FALSE
        WHERE driver = 'docker'
            AND connection_id = %s
            AND target_kind = 'standalone_container'
            AND target = ANY(%s::varchar[])
        """,
        (connection_id, member_docker_ids),
    )


def _mark_targets_absent(
    cursor,
    connection_id: str,
    observed_ids: list[int],
) -> int:
    cursor.execute(
        """
        UPDATE targets
        SET is_present = FALSE
        WHERE driver = 'docker'
            AND connection_id = %s
            AND is_present = TRUE
            AND NOT (id = ANY(%s::integer[]))
        """,
        (connection_id, observed_ids),
    )
    return cursor.rowcount


def _mark_rows_absent(
    cursor,
    table_name: str,
    connection_id: str,
    observed_ids: list[int],
) -> int:
    if table_name not in {"compose_members", "docker_inventory_issues"}:
        raise ValueError("unsupported inventory table")
    cursor.execute(
        f"""
        UPDATE {table_name}
        SET is_present = FALSE
        WHERE connection_id = %s
            AND is_present = TRUE
            AND NOT (id = ANY(%s::integer[]))
        """,
        (connection_id, observed_ids),
    )
    return cursor.rowcount
