CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(20) NOT NULL UNIQUE,
    type VARCHAR(20) NOT NULL,
    category VARCHAR(20) NOT NULL,
    description VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'off',
    dependencies INTEGER[] NULL,
    device_dependencies INTEGER[] NULL
);

CREATE TABLE IF NOT EXISTS agent_connections (
    id VARCHAR(100) PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    description VARCHAR(200) NOT NULL,
    transport VARCHAR(20) NOT NULL,
    endpoint VARCHAR(500) NOT NULL,
    credential_ref VARCHAR(100) NULL,
    default_management_policy VARCHAR(20) NOT NULL DEFAULT 'discovered',
    CHECK (transport IN ('unix_socket', 'https')),
    CHECK (default_management_policy = 'discovered'),
    CONSTRAINT agent_connections_agent_id_format CHECK (
        agent_id ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$'
    ),
    CONSTRAINT agent_connections_credential_ref_format CHECK (
        credential_ref IS NULL
        OR credential_ref ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$'
    )
);

CREATE TABLE IF NOT EXISTS targets (
    id SERIAL PRIMARY KEY,
    driver VARCHAR(50) NOT NULL,
    connection_id VARCHAR(100) NOT NULL REFERENCES agent_connections(id),
    target VARCHAR(255) NOT NULL,
    management_policy VARCHAR(20) NOT NULL DEFAULT 'discovered',
    display_name VARCHAR(255) NULL,
    observed_state VARCHAR(20) NULL,
    observed_health_status VARCHAR(20) NULL,
    last_seen_at TIMESTAMPTZ NULL,
    is_present BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (management_policy IN ('discovered', 'managed', 'protected')),
    CONSTRAINT targets_observed_state_allowed CHECK (
        observed_state IS NULL OR observed_state IN (
            'created', 'running', 'paused', 'restarting',
            'removing', 'exited', 'dead', 'unknown'
        )
    ),
    CONSTRAINT targets_observed_health_allowed CHECK (
        observed_health_status IS NULL OR observed_health_status IN (
            'none', 'starting', 'healthy', 'unhealthy', 'unknown'
        )
    ),
    UNIQUE (driver, connection_id, target)
);

CREATE OR REPLACE FUNCTION reject_target_identity_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.driver IS DISTINCT FROM OLD.driver
        OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
        OR NEW.target IS DISTINCT FROM OLD.target THEN
        RAISE EXCEPTION 'target operational identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS targets_identity_immutable ON targets;
CREATE TRIGGER targets_identity_immutable
BEFORE UPDATE ON targets
FOR EACH ROW
EXECUTE FUNCTION reject_target_identity_update();

CREATE TABLE IF NOT EXISTS service_targets (
    service_id INTEGER PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL UNIQUE REFERENCES targets(id),
    readiness_check VARCHAR(20) NOT NULL DEFAULT 'docker_state',
    CHECK (
        readiness_check IN ('docker_state', 'docker_health', 'http', 'tcp')
    )
);

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id),
    target_id INTEGER NULL REFERENCES targets(id) ON DELETE RESTRICT,
    action VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_by_type VARCHAR(20) NOT NULL DEFAULT 'unknown',
    requested_by_id VARCHAR(100) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    error_message TEXT NULL,
    queue_duration_ms BIGINT NULL CHECK (queue_duration_ms >= 0),
    execution_duration_ms BIGINT NULL CHECK (execution_duration_ms >= 0),
    verification_duration_ms BIGINT NULL CHECK (verification_duration_ms >= 0),
    total_duration_ms BIGINT NULL CHECK (total_duration_ms >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_service
ON jobs (service_id)
WHERE status IN ('pending', 'running');

CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_target
ON jobs (target_id)
WHERE target_id IS NOT NULL AND status IN ('pending', 'running');

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
);

INSERT INTO services (name, type, category, description, status)
VALUES
    ('steampunk', 'LXC', 'game', 'serveur minecraft sur le theme steampunk', 'off'),
    ('stefano', 'VM', 'tool', 'outil de developpement pour le projet stefano', 'on')
ON CONFLICT (name) DO NOTHING;
