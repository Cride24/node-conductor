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
    description VARCHAR(200) NOT NULL,
    transport VARCHAR(20) NOT NULL,
    endpoint VARCHAR(500) NOT NULL,
    default_management_policy VARCHAR(20) NOT NULL DEFAULT 'discovered',
    CHECK (transport IN ('unix_socket', 'https')),
    CHECK (default_management_policy = 'discovered')
);

CREATE TABLE IF NOT EXISTS targets (
    id SERIAL PRIMARY KEY,
    driver VARCHAR(50) NOT NULL,
    connection_id VARCHAR(100) NOT NULL REFERENCES agent_connections(id),
    target VARCHAR(255) NOT NULL,
    management_policy VARCHAR(20) NOT NULL DEFAULT 'discovered',
    CHECK (management_policy IN ('discovered', 'managed', 'protected')),
    UNIQUE (driver, connection_id, target)
);

CREATE TABLE IF NOT EXISTS service_targets (
    service_id INTEGER PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES targets(id),
    readiness_check VARCHAR(20) NOT NULL DEFAULT 'docker_state',
    CHECK (
        readiness_check IN ('docker_state', 'docker_health', 'http', 'tcp')
    )
);

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
    error_message TEXT NULL,
    queue_duration_ms BIGINT NULL CHECK (queue_duration_ms >= 0),
    execution_duration_ms BIGINT NULL CHECK (execution_duration_ms >= 0),
    verification_duration_ms BIGINT NULL CHECK (verification_duration_ms >= 0),
    total_duration_ms BIGINT NULL CHECK (total_duration_ms >= 0)
);

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
