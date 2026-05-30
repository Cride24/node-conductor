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
    return psycopg.connect(settings.database_url, row_factory=dict_row)


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
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE services RESTART IDENTITY")
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
