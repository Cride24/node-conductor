"""Acces aux donnees brutes des events."""

from psycopg.types.json import Jsonb

from nodeconductor.repositories.services_repository import _connect, ensure_events_table


EVENT_COLUMNS = """
    id,
    event_type,
    severity,
    message,
    service_id,
    job_id,
    actor_type,
    actor_id,
    created_at,
    details
"""


def create_event(
    event_type: str,
    severity: str,
    message: str,
    service_id: int | None = None,
    job_id: int | None = None,
    actor_type: str = "unknown",
    actor_id: str | None = None,
    details: dict | None = None,
) -> dict:
    ensure_events_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO events (
                    event_type,
                    severity,
                    message,
                    service_id,
                    job_id,
                    actor_type,
                    actor_id,
                    details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {EVENT_COLUMNS}
                """,
                (
                    event_type,
                    severity,
                    message,
                    service_id,
                    job_id,
                    actor_type,
                    actor_id,
                    Jsonb(details) if details is not None else None,
                ),
            )
            return cursor.fetchone()


def fetch_events(
    service_id: int | None = None,
    job_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    ensure_events_table()
    clauses = []
    params: dict[str, int] = {"limit": limit}
    if service_id is not None:
        clauses.append("service_id = %(service_id)s")
        params["service_id"] = service_id
    if job_id is not None:
        clauses.append("job_id = %(job_id)s")
        params["job_id"] = job_id

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {EVENT_COLUMNS}
                FROM events
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %(limit)s
                """,
                params,
            )
            return list(cursor.fetchall())
