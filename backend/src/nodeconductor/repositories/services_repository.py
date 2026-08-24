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
    options = (
        f"-c statement_timeout={settings.database_statement_timeout_ms} "
        f"-c lock_timeout={settings.database_lock_timeout_ms}"
    )
    return psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        connect_timeout=settings.database_connect_timeout_seconds,
        options=options,
    )


def ensure_jobs_table() -> None:
    """Cree la table jobs si la base locale existait avant son introduction."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    service_id INTEGER NOT NULL REFERENCES services(id),
                    operation_id UUID NULL,
                    action VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    requested_by_type VARCHAR(20) NOT NULL DEFAULT 'unknown',
                    requested_by_id VARCHAR(100) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    error_message TEXT NULL,
                    queue_duration_ms BIGINT NULL CHECK (queue_duration_ms >= 0),
                    execution_duration_ms BIGINT NULL CHECK (
                        execution_duration_ms >= 0
                    ),
                    verification_duration_ms BIGINT NULL CHECK (
                        verification_duration_ms >= 0
                    ),
                    total_duration_ms BIGINT NULL CHECK (total_duration_ms >= 0)
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE jobs
                    ADD COLUMN IF NOT EXISTS operation_id UUID NULL,
                    ADD COLUMN IF NOT EXISTS queue_duration_ms BIGINT NULL
                        CHECK (queue_duration_ms >= 0),
                    ADD COLUMN IF NOT EXISTS execution_duration_ms BIGINT NULL
                        CHECK (execution_duration_ms >= 0),
                    ADD COLUMN IF NOT EXISTS verification_duration_ms BIGINT NULL
                        CHECK (verification_duration_ms >= 0),
                    ADD COLUMN IF NOT EXISTS total_duration_ms BIGINT NULL
                        CHECK (total_duration_ms >= 0)
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_operation_id_unique
                ON jobs (operation_id)
                WHERE operation_id IS NOT NULL
                """
            )


def ensure_worker_contracts_schema() -> None:
    """Ajoute les tables du lot contrats sans activer de connecteur reel."""
    ensure_jobs_table()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_connections (
                    id VARCHAR(100) PRIMARY KEY,
                    agent_id VARCHAR(100) NOT NULL,
                    description VARCHAR(200) NOT NULL,
                    transport VARCHAR(20) NOT NULL,
                    endpoint VARCHAR(500) NOT NULL,
                    credential_ref VARCHAR(100) NULL,
                    default_management_policy VARCHAR(20) NOT NULL
                        DEFAULT 'discovered',
                    CHECK (transport IN ('unix_socket', 'https')),
                    CHECK (default_management_policy = 'discovered')
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id SERIAL PRIMARY KEY,
                    driver VARCHAR(50) NOT NULL,
                    connection_id VARCHAR(100) NOT NULL
                        REFERENCES agent_connections(id),
                    target_kind VARCHAR(30) NOT NULL
                        DEFAULT 'standalone_container',
                    target VARCHAR(255) NOT NULL,
                    management_policy VARCHAR(20) NOT NULL
                        DEFAULT 'discovered',
                    display_name VARCHAR(255) NULL,
                    observed_state VARCHAR(20) NULL,
                    observed_health_status VARCHAR(20) NULL,
                    last_seen_at TIMESTAMPTZ NULL,
                    is_present BOOLEAN NOT NULL DEFAULT FALSE,
                    is_pilotable BOOLEAN NOT NULL DEFAULT TRUE,
                    protection_forced BOOLEAN NOT NULL DEFAULT FALSE,
                    CHECK (
                        management_policy IN (
                            'discovered',
                            'managed',
                            'protected'
                        )
                    ),
                    CHECK (
                        target_kind IN (
                            'compose_project',
                            'standalone_container'
                        )
                    ),
                    UNIQUE (driver, connection_id, target_kind, target)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS service_targets (
                    service_id INTEGER PRIMARY KEY
                        REFERENCES services(id) ON DELETE CASCADE,
                    target_id INTEGER NOT NULL UNIQUE REFERENCES targets(id),
                    readiness_check VARCHAR(20) NOT NULL DEFAULT 'docker_state',
                    CHECK (
                        readiness_check IN (
                            'docker_state',
                            'docker_health',
                            'http',
                            'tcp'
                        )
                    )
                )
                """
            )


def ensure_worker_concurrency_schema() -> None:
    """Ajoute les invariants PostgreSQL du worker concurrent."""
    ensure_worker_contracts_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    service_targets_one_service_per_target
                ON service_targets (target_id)
                """
            )
            cursor.execute(
                """
                ALTER TABLE jobs
                    ADD COLUMN IF NOT EXISTS target_id INTEGER NULL
                        REFERENCES targets(id) ON DELETE RESTRICT
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_service
                ON jobs (service_id)
                WHERE status IN ('pending', 'running')
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_target
                ON jobs (target_id)
                WHERE target_id IS NOT NULL
                    AND status IN ('pending', 'running')
                """
            )
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION reject_target_identity_update()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF NEW.driver IS DISTINCT FROM OLD.driver
                        OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
                        OR NEW.target_kind IS DISTINCT FROM OLD.target_kind
                        OR NEW.target IS DISTINCT FROM OLD.target THEN
                        RAISE EXCEPTION
                            'target operational identity is immutable'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_trigger
                        WHERE tgname = 'targets_identity_immutable'
                            AND tgrelid = 'targets'::regclass
                    ) THEN
                        CREATE TRIGGER targets_identity_immutable
                        BEFORE UPDATE ON targets
                        FOR EACH ROW
                        EXECUTE FUNCTION reject_target_identity_update();
                    END IF;
                END;
                $$
                """
            )


def ensure_agent_sync_schema() -> None:
    """Ajoute l'identite Agent et les observations d'inventaire du lot 3B."""
    ensure_worker_concurrency_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE agent_connections
                    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(100) NULL,
                    ADD COLUMN IF NOT EXISTS credential_ref VARCHAR(100) NULL
                """
            )
            cursor.execute(
                """
                UPDATE agent_connections
                SET agent_id = id
                WHERE agent_id IS NULL
                """
            )
            cursor.execute(
                """
                ALTER TABLE agent_connections
                    ALTER COLUMN agent_id SET NOT NULL
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'agent_connections_agent_id_format'
                            AND conrelid = 'agent_connections'::regclass
                    ) THEN
                        ALTER TABLE agent_connections ADD CONSTRAINT
                            agent_connections_agent_id_format CHECK (
                                agent_id ~
                                    '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$'
                            );
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname =
                            'agent_connections_credential_ref_format'
                            AND conrelid = 'agent_connections'::regclass
                    ) THEN
                        ALTER TABLE agent_connections ADD CONSTRAINT
                            agent_connections_credential_ref_format CHECK (
                                credential_ref IS NULL OR credential_ref ~
                                    '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$'
                            );
                    END IF;
                END;
                $$
                """
            )
            cursor.execute(
                """
                ALTER TABLE targets
                    ADD COLUMN IF NOT EXISTS target_kind VARCHAR(30) NOT NULL
                        DEFAULT 'standalone_container',
                    ADD COLUMN IF NOT EXISTS display_name VARCHAR(255) NULL,
                    ADD COLUMN IF NOT EXISTS observed_state VARCHAR(20) NULL,
                    ADD COLUMN IF NOT EXISTS
                        observed_health_status VARCHAR(20) NULL,
                    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL,
                    ADD COLUMN IF NOT EXISTS is_present BOOLEAN NOT NULL
                        DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS is_pilotable BOOLEAN NOT NULL
                        DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS protection_forced BOOLEAN NOT NULL
                        DEFAULT FALSE
                """
            )
            cursor.execute(
                """
                ALTER TABLE targets
                    DROP CONSTRAINT IF EXISTS
                        targets_driver_connection_id_target_key;
                CREATE UNIQUE INDEX IF NOT EXISTS targets_typed_identity_unique
                ON targets (driver, connection_id, target_kind, target);
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'targets_target_kind_allowed'
                            AND conrelid = 'targets'::regclass
                    ) THEN
                        ALTER TABLE targets ADD CONSTRAINT
                            targets_target_kind_allowed CHECK (
                                target_kind IN (
                                    'compose_project',
                                    'standalone_container'
                                )
                            );
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'targets_observed_state_allowed'
                            AND conrelid = 'targets'::regclass
                    ) OR NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'targets_observed_state_allowed'
                            AND conrelid = 'targets'::regclass
                            AND pg_get_constraintdef(oid) LIKE '%partial%'
                    ) THEN
                        ALTER TABLE targets DROP CONSTRAINT IF EXISTS
                            targets_observed_state_allowed;
                        ALTER TABLE targets ADD CONSTRAINT
                            targets_observed_state_allowed CHECK (
                                observed_state IS NULL OR observed_state IN (
                                    'created', 'running', 'paused',
                                    'restarting', 'removing', 'exited', 'dead',
                                    'stopped', 'starting', 'degraded',
                                    'partial', 'unknown'
                                )
                            );
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'targets_observed_health_allowed'
                            AND conrelid = 'targets'::regclass
                    ) THEN
                        ALTER TABLE targets ADD CONSTRAINT
                            targets_observed_health_allowed CHECK (
                                observed_health_status IS NULL
                                OR observed_health_status IN (
                                    'none', 'starting', 'healthy',
                                    'unhealthy', 'unknown'
                                )
                            );
                    END IF;
                END;
                $$
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS compose_members (
                    id SERIAL PRIMARY KEY,
                    connection_id VARCHAR(100) NOT NULL
                        REFERENCES agent_connections(id),
                    project_target_id INTEGER NOT NULL
                        REFERENCES targets(id) ON DELETE CASCADE,
                    docker_id VARCHAR(64) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    compose_service VARCHAR(255) NOT NULL,
                    observed_state VARCHAR(20) NOT NULL,
                    observed_health_status VARCHAR(20) NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    is_present BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (connection_id, docker_id)
                );

                CREATE TABLE IF NOT EXISTS docker_inventory_issues (
                    id SERIAL PRIMARY KEY,
                    connection_id VARCHAR(100) NOT NULL
                        REFERENCES agent_connections(id),
                    docker_id VARCHAR(64) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    observed_state VARCHAR(20) NOT NULL,
                    observed_health_status VARCHAR(20) NOT NULL,
                    diagnostic_status VARCHAR(80) NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    is_present BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (connection_id, docker_id)
                );
                """
            )
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION enforce_target_protection()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF OLD.protection_forced
                        AND (
                            NOT NEW.protection_forced
                            OR NEW.management_policy <> 'protected'
                        ) THEN
                        RAISE EXCEPTION
                            'forced target protection cannot be removed'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;

                CREATE OR REPLACE FUNCTION require_pilotable_service_target()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM targets
                        WHERE id = NEW.target_id AND is_pilotable
                    ) THEN
                        RAISE EXCEPTION
                            'service target must be pilotable'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;

                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'targets_protection_forced'
                            AND tgrelid = 'targets'::regclass
                    ) THEN
                        CREATE TRIGGER targets_protection_forced
                        BEFORE UPDATE OF management_policy ON targets
                        FOR EACH ROW
                        EXECUTE FUNCTION enforce_target_protection();
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'targets_protection_flag_immutable'
                            AND tgrelid = 'targets'::regclass
                    ) THEN
                        CREATE TRIGGER targets_protection_flag_immutable
                        BEFORE UPDATE OF protection_forced ON targets
                        FOR EACH ROW
                        EXECUTE FUNCTION enforce_target_protection();
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'service_targets_pilotable'
                            AND tgrelid = 'service_targets'::regclass
                    ) THEN
                        CREATE TRIGGER service_targets_pilotable
                        BEFORE INSERT OR UPDATE OF target_id
                        ON service_targets
                        FOR EACH ROW
                        EXECUTE FUNCTION require_pilotable_service_target();
                    END IF;
                END;
                $$;
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


def count_rows() -> int:
    """Compte les services sans charger toutes les lignes en memoire."""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM services")
            return cursor.fetchone()["total"]


def fetch_rows_page(limit: int, offset: int) -> list[dict]:
    """Liste une page bornee de services."""
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
                LIMIT %s
                OFFSET %s
                """,
                (limit, offset),
            )
            return list(cursor.fetchall())


def reset_rows() -> None:
    """Utile pour isoler les tests automatises."""
    ensure_events_table()
    ensure_agent_sync_schema()
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    events,
                    jobs,
                    service_targets,
                    compose_members,
                    docker_inventory_issues,
                    services,
                    targets,
                    agent_connections
                RESTART IDENTITY
                """
            )
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
