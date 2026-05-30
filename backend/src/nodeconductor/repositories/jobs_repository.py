"""Acces aux donnees brutes des jobs."""

from nodeconductor.repositories.services_repository import _connect, ensure_jobs_table


JOB_COLUMNS = """
    id,
    service_id,
    action,
    status,
    requested_by_type,
    requested_by_id,
    created_at,
    started_at,
    finished_at,
    error_message
"""


def _build_job(row: dict | None) -> dict | None:
    return row


def fetch_job_by_id(job_id: int) -> dict | None:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {JOB_COLUMNS}
                FROM jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            return _build_job(cursor.fetchone())


def fetch_active_job_for_service(service_id: int) -> dict | None:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {JOB_COLUMNS}
                FROM jobs
                WHERE service_id = %s
                    AND status IN ('pending', 'running')
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (service_id,),
            )
            return _build_job(cursor.fetchone())


def create_job_for_service(
    service_id: int,
    action: str,
    requested_by_type: str = "unknown",
    requested_by_id: str | None = None,
) -> dict:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO jobs (
                    service_id,
                    action,
                    requested_by_type,
                    requested_by_id
                )
                VALUES (%s, %s, %s, %s)
                RETURNING {JOB_COLUMNS}
                """,
                (service_id, action, requested_by_type, requested_by_id),
            )
            return cursor.fetchone()


def cancel_pending_job(job_id: int) -> dict | None:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET
                    status = 'cancelled',
                    finished_at = now()
                WHERE id = %s
                    AND status = 'pending'
                RETURNING {JOB_COLUMNS}
                """,
                (job_id,),
            )
            return _build_job(cursor.fetchone())


def mark_job_running(job_id: int) -> dict | None:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET
                    status = 'running',
                    started_at = now()
                WHERE id = %s
                    AND status = 'pending'
                RETURNING {JOB_COLUMNS}
                """,
                (job_id,),
            )
            return _build_job(cursor.fetchone())


def finish_running_job(
    job_id: int,
    status: str,
    error_message: str | None = None,
) -> dict | None:
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET
                    status = %s,
                    finished_at = now(),
                    error_message = %s
                WHERE id = %s
                    AND status = 'running'
                RETURNING {JOB_COLUMNS}
                """,
                (status, error_message, job_id),
            )
            return _build_job(cursor.fetchone())
