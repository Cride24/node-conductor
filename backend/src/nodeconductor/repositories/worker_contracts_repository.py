"""Persistance minimale des connexions, cibles et associations de services."""

from nodeconductor.repositories.services_repository import (
    _connect,
    ensure_worker_concurrency_schema,
)


def create_agent_connection_row(connection: dict) -> dict:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_connections (
                    id,
                    description,
                    transport,
                    endpoint
                )
                VALUES (%(id)s, %(description)s, %(transport)s, %(endpoint)s)
                RETURNING
                    id,
                    description,
                    transport,
                    endpoint,
                    default_management_policy
                """,
                connection,
            )
            return cursor.fetchone()


def create_target_row(target: dict) -> dict:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO targets (driver, connection_id, target)
                VALUES (%(driver)s, %(connection_id)s, %(target)s)
                RETURNING
                    id,
                    driver,
                    connection_id,
                    target,
                    management_policy
                """,
                target,
            )
            return cursor.fetchone()


def update_target_management_policy_row(target_id: int, policy: str) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE targets
                SET management_policy = %s
                WHERE id = %s
                RETURNING
                    id,
                    driver,
                    connection_id,
                    target,
                    management_policy
                """,
                (policy, target_id),
            )
            return cursor.fetchone()


def create_service_target_binding_row(binding: dict) -> dict:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            # Serialise l'association avec la creation atomique d'un job.
            cursor.execute(
                "SELECT id FROM services WHERE id = %s FOR UPDATE",
                (binding["service_id"],),
            )
            cursor.execute(
                """
                INSERT INTO service_targets (service_id, target_id, readiness_check)
                VALUES (%(service_id)s, %(target_id)s, %(readiness_check)s)
                RETURNING service_id, target_id, readiness_check
                """,
                binding,
            )
            return cursor.fetchone()


def fetch_service_target_binding_row(service_id: int) -> dict | None:
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    service_targets.service_id,
                    services.description AS service_description,
                    service_targets.target_id,
                    service_targets.readiness_check
                FROM service_targets
                JOIN services ON services.id = service_targets.service_id
                WHERE service_targets.service_id = %s
                """,
                (service_id,),
            )
            return cursor.fetchone()
