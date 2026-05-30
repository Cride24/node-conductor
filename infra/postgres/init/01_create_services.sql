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
);

INSERT INTO services (name, type, category, description, status)
VALUES
    ('steampunk', 'LXC', 'game', 'serveur minecraft sur le theme steampunk', 'off'),
    ('stefano', 'VM', 'tool', 'outil de developpement pour le projet stefano', 'on')
ON CONFLICT (name) DO NOTHING;
