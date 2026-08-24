"""Acces PostgreSQL aux jobs et aux invariants de concurrence."""

from uuid import UUID, uuid4

from nodeconductor.repositories.services_repository import (
    _connect,
    ensure_worker_concurrency_schema,
)


_CLAIM_ADVISORY_LOCK_ID = 1_314_624_435

JOB_COLUMNS = """
    id,
    service_id,
    target_id,
    operation_id,
    action,
    status,
    requested_by_type,
    requested_by_id,
    created_at,
    started_at,
    finished_at,
    error_message,
    queue_duration_ms,
    execution_duration_ms,
    verification_duration_ms,
    total_duration_ms
"""

CLAIMED_JOB_COLUMNS = """
    claimed.id,
    claimed.service_id,
    claimed.target_id,
    claimed.operation_id,
    claimed.action,
    claimed.status,
    claimed.requested_by_type,
    claimed.requested_by_id,
    claimed.created_at,
    claimed.started_at,
    claimed.finished_at,
    claimed.error_message,
    claimed.queue_duration_ms,
    claimed.execution_duration_ms,
    claimed.verification_duration_ms,
    claimed.total_duration_ms
"""


def fetch_job_by_id(job_id: int) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s",
                (job_id,),
            )
            return cursor.fetchone()


def _fetch_target_id(cursor, service_id: int) -> int | None:
    cursor.execute(
        "SELECT target_id FROM service_targets WHERE service_id = %s",
        (service_id,),
    )
    binding = cursor.fetchone()
    return None if binding is None else binding["target_id"]


def _target_is_pilotable(cursor, target_id: int | None) -> bool:
    if target_id is None:
        return True
    cursor.execute(
        "SELECT is_pilotable FROM targets WHERE id = %s",
        (target_id,),
    )
    row = cursor.fetchone()
    return row is not None and row["is_pilotable"]


def _fetch_active_job(cursor, service_id: int, target_id: int | None) -> dict | None:
    cursor.execute(
        f"""
        SELECT {JOB_COLUMNS}
        FROM jobs
        WHERE status IN ('pending', 'running')
            AND (
                service_id = %s
                OR (target_id IS NOT NULL AND target_id = %s)
            )
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """,
        (service_id, target_id),
    )
    return cursor.fetchone()


def fetch_active_job_for_service(service_id: int) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            target_id = _fetch_target_id(cursor, service_id)
            return _fetch_active_job(cursor, service_id, target_id)


def request_job_for_service_atomically(
    service_id: int,
    action: str,
    required_service_status: str,
    requested_by_type: str = "unknown",
    requested_by_id: str | None = None,
) -> dict:
    """Verrouille le service, puis retourne l'actif ou cree un seul job."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, status FROM services WHERE id = %s FOR UPDATE",
                (service_id,),
            )
            service = cursor.fetchone()
            if service is None:
                return {"outcome": "missing", "service_status": None, "job": None}

            target_id = _fetch_target_id(cursor, service_id)
            if not _target_is_pilotable(cursor, target_id):
                return {
                    "outcome": "target_not_pilotable",
                    "service_status": service["status"],
                    "job": None,
                }
            active_job = _fetch_active_job(cursor, service_id, target_id)
            if active_job is not None:
                return {
                    "outcome": "active",
                    "service_status": service["status"],
                    "job": active_job,
                }
            if service["status"] != required_service_status:
                return {
                    "outcome": "state",
                    "service_status": service["status"],
                    "job": None,
                }

            cursor.execute(
                f"""
                INSERT INTO jobs (
                    service_id,
                    target_id,
                    action,
                    requested_by_type,
                    requested_by_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {JOB_COLUMNS}
                """,
                (
                    service_id,
                    target_id,
                    action,
                    requested_by_type,
                    requested_by_id,
                ),
            )
            return {
                "outcome": "created",
                "service_status": service["status"],
                "job": cursor.fetchone(),
            }


def fetch_next_pending_job() -> dict | None:
    """Lecture de compatibilite; le worker automatique utilise le claim atomique."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {JOB_COLUMNS}
                FROM jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            )
            return cursor.fetchone()


def create_job_for_service(
    service_id: int,
    action: str,
    requested_by_type: str = "unknown",
    requested_by_id: str | None = None,
) -> dict:
    """Facade bas niveau conservee pour les tests et outils internes."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            target_id = _fetch_target_id(cursor, service_id)
            if not _target_is_pilotable(cursor, target_id):
                raise ValueError("service target is not pilotable")
            cursor.execute(
                f"""
                INSERT INTO jobs (
                    service_id,
                    target_id,
                    action,
                    requested_by_type,
                    requested_by_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {JOB_COLUMNS}
                """,
                (
                    service_id,
                    target_id,
                    action,
                    requested_by_type,
                    requested_by_id,
                ),
            )
            return cursor.fetchone()


def cancel_pending_job(job_id: int) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET status = 'cancelled', finished_at = now()
                WHERE id = %s AND status = 'pending'
                RETURNING {JOB_COLUMNS}
                """,
                (job_id,),
            )
            return cursor.fetchone()


def claim_pending_job(job_id: int) -> dict | None:
    """Claim atomique d'un job precis pour les facades manuelles."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET
                    status = 'running',
                    started_at = now(),
                    operation_id = COALESCE(operation_id, %s)
                WHERE id = %s AND status = 'pending'
                RETURNING {JOB_COLUMNS}
                """,
                (uuid4(), job_id),
            )
            return cursor.fetchone()


def ensure_running_job_operation_id(
    job_id: int,
    candidate: UUID | None = None,
) -> dict | None:
    """Persiste une seule identite avant dispatch, y compris pour un ancien job."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET operation_id = COALESCE(operation_id, %s)
                WHERE id = %s AND status = 'running'
                RETURNING {JOB_COLUMNS}
                """,
                (candidate if candidate is not None else uuid4(), job_id),
            )
            return cursor.fetchone()


def _global_capacity_available(cursor, max_concurrency: int) -> bool:
    cursor.execute("SELECT COUNT(*) AS total FROM jobs WHERE status = 'running'")
    return cursor.fetchone()["total"] < max_concurrency


def claim_next_pending_job(
    max_concurrency: int,
    max_concurrency_per_connection: int,
) -> dict | None:
    """Claim le prochain job admissible dans une seule transaction PostgreSQL."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            # Toutes les instances partagent cette courte section de capacite.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_CLAIM_ADVISORY_LOCK_ID,),
            )
            if not _global_capacity_available(cursor, max_concurrency):
                return None
            cursor.execute(
                f"""
                WITH candidate AS (
                    SELECT pending.id
                    FROM jobs AS pending
                    LEFT JOIN targets AS pending_target
                        ON pending_target.id = pending.target_id
                    WHERE pending.status = 'pending'
                        AND (
                            pending.target_id IS NULL
                            OR pending_target.is_pilotable
                        )
                        AND (
                            pending_target.connection_id IS NULL
                            OR (
                                SELECT COUNT(*)
                                FROM jobs AS running
                                JOIN targets AS running_target
                                    ON running_target.id = running.target_id
                                WHERE running.status = 'running'
                                    AND running_target.connection_id =
                                        pending_target.connection_id
                            ) < %s
                        )
                    ORDER BY pending.created_at ASC, pending.id ASC
                    FOR UPDATE OF pending SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs AS claimed
                SET
                    status = 'running',
                    started_at = now(),
                    operation_id = COALESCE(claimed.operation_id, %s)
                FROM candidate
                WHERE claimed.id = candidate.id
                    AND claimed.status = 'pending'
                RETURNING {CLAIMED_JOB_COLUMNS}
                """,
                (max_concurrency_per_connection, uuid4()),
            )
            return cursor.fetchone()


def finish_running_job(
    job_id: int,
    status: str,
    error_message: str | None = None,
) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET status = %s, finished_at = now(), error_message = %s
                WHERE id = %s AND status = 'running'
                RETURNING {JOB_COLUMNS}
                """,
                (status, error_message, job_id),
            )
            return cursor.fetchone()
