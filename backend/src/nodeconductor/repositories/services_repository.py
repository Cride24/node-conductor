"""Acces aux donnees brutes des services."""

import psycopg
from psycopg.rows import dict_row

from nodeconductor.core.config import settings


_INITIAL_ROWS: list[dict] = [
    {
        "id": 1,
        "name": "steampunk",
        "type": "LXC",
        "category": "game",
        "description": "serveur minecraft sur le theme steampunk",
        "status": "off",
    },
    {
        "id": 2,
        "name": "stefano",
        "type": "VM",
        "category": "tool",
        "description": "outil de developpement pour le projet stefano",
        "status": "on",
    },
]


def _connect() -> psycopg.Connection:
    # Voir Docs/PostgreSQL-Docker-Quickstart.md pour le lancement local.
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def ensure_jobs_table() -> None:
    """Cree la table jobs si la base locale existait avant son introduction."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    service_id INTEGER NOT NULL REFERENCES services(id),
                    action VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    requested_by_type VARCHAR(20) NOT NULL DEFAULT 'unknown',
                    requested_by_id VARCHAR(100) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    error_message TEXT NULL
                )
                """
            )


def ensure_events_table() -> None:
    """Cree la table events si la base locale existait avant son introduction."""
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    event_type VARCHAR(80) NOT NULL,
                    severity VARCHAR(20) NOT NULL,
                    message TEXT NOT NULL,
                    service_id INTEGER NULL REFERENCES services(id),
                    job_id INTEGER NULL REFERENCES jobs(id),
                    actor_type VARCHAR(20) NOT NULL DEFAULT 'unknown',
                    actor_id VARCHAR(100) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    details JSONB NULL
                )
                """
            )


def fetch_all_rows() -> list[dict]:
    """Liste complete (pour listing tolerant)."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                FROM services
                ORDER BY id
                """
            )
            return list(cursor.fetchall())


def reset_rows() -> None:
    """Utile pour isoler les tests automatises."""
    ensure_events_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE events, jobs, services RESTART IDENTITY")
            for row in _INITIAL_ROWS:
                cursor.execute(
                    """
                    INSERT INTO services (
                        name,
                        type,
                        category,
                        description,
                        status
                    )
                    VALUES (
                        %(name)s,
                        %(type)s,
                        %(category)s,
                        %(description)s,
                        %(status)s
                    )
                    """,
                    row,
                )


def fetch_row_by_id(service_id: int) -> dict | None:
    """Une ligne par id."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                FROM services
                WHERE id = %s
                """,
                (service_id,),
            )
            return cursor.fetchone()


def update_service_status_row(service_id: int, status: str) -> dict | None:
    """Met a jour l'etat interne d'un service depuis le worker ou sa simulation."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE services
                SET status = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                """,
                (status, service_id),
            )
            return cursor.fetchone()


def fetch_row_by_name(service_name: str) -> dict | None:
    """Une ligne par nom (utile pour verifier l'unicite metier)."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                FROM services
                WHERE name = %s
                """,
                (service_name,),
            )
            return cursor.fetchone()


def add_service(service: dict) -> dict:
    """
    Insere un service:
    - l'id est genere cote persistance,
    - le status par defaut est initialise par PostgreSQL.
    """
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO services (
                    name,
                    type,
                    category,
                    description,
                    dependencies,
                    device_dependencies
                )
                VALUES (
                    %(name)s,
                    %(type)s,
                    %(category)s,
                    %(description)s,
                    %(dependencies)s,
                    %(device_dependencies)s
                )
                RETURNING
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                """,
                service,
            )
            return cursor.fetchone()


def update_service_row(service_id: int, updates: dict) -> dict | None:
    """Met a jour une ligne service et renvoie la ligne modifiee."""
    # status est absent ici par conception: les actions metier en sont proprietaires.
    allowed_fields = (
        "name",
        "type",
        "category",
        "description",
        "dependencies",
        "device_dependencies",
    )
    unknown_fields = set(updates) - set(allowed_fields)
    if unknown_fields:
        raise ValueError(f"Unknown update fields: {sorted(unknown_fields)}")

    assignments = [
        f"{field} = %({field})s"
        for field in allowed_fields
        if field in updates
    ]
    params = {**updates, "service_id": service_id}

    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE services
                SET {", ".join(assignments)}
                WHERE id = %(service_id)s
                RETURNING
                    id,
                    name,
                    type,
                    category,
                    description,
                    status,
                    dependencies,
                    device_dependencies
                """,
                params,
            )
            return cursor.fetchone()
