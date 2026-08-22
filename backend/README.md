## NodeConductor Backend

Backend FastAPI (MVP) pour le projet **NodeConductor**.

### Lancer en dev

```bash
poetry install
poetry run uvicorn nodeconductor.main:app --reload
```

### Endpoints

- `GET /api/v1/health`
- `GET /api/v1/version`
- `GET /api/v1/services?limit=50&offset=0`
- `GET /api/v1/services/{service_id}`
- `POST /api/v1/services/`
- `PATCH /api/v1/services/{service_id}`
- `POST /api/v1/services/{service_id}/start`
- `POST /api/v1/services/{service_id}/stop`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/cancel`
- `POST /api/v1/jobs/{job_id}/simulate-complete`

### Lancer les tests

```bash
poetry run pytest
```

### Configuration

Variables principales :

```env
NODECONDUCTOR_DATABASE_URL=postgresql://nodeconductor:nodeconductor_dev@localhost:5432/nodeconductor
NODECONDUCTOR_WORKER_MODE=simulation
NODECONDUCTOR_EVENT_LEVEL=info
NODECONDUCTOR_WORKER_AUTO_ENABLED=false
NODECONDUCTOR_WORKER_POLL_INTERVAL_SECONDS=5
NODECONDUCTOR_API_MAX_REQUEST_BODY_BYTES=65536
NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS=10
NODECONDUCTOR_DATABASE_CONNECT_TIMEOUT_SECONDS=3
NODECONDUCTOR_DATABASE_STATEMENT_TIMEOUT_MS=5000
NODECONDUCTOR_DATABASE_LOCK_TIMEOUT_MS=2000
NODECONDUCTOR_WORKER_EXECUTION_TIMEOUT_SECONDS=30
```

Les listes de services sont paginees (`limit` entre 1 et 200). Les corps HTTP
trop volumineux renvoient `413`, une requete API trop longue renvoie `504`, et
les operations PostgreSQL/worker disposent de leurs propres delais configurables.

`NODECONDUCTOR_WORKER_MODE` accepte :

- `simulation` : mode par defaut, sans action infrastructure reelle ;
- `real` : futur mode reel, prepare mais non branche dans le MVP actuel.

Une instance NodeConductor utilise une seule base PostgreSQL. Une demonstration
simulee doit donc avoir sa propre instance, son propre conteneur et sa propre
base fictive, separes de l'environnement reel.

`NODECONDUCTOR_EVENT_LEVEL` accepte :

- `info` : events metier sobres et tracables ;
- `debug` : reserve aux futurs details techniques du worker et des connecteurs.

### PostgreSQL local

Le backend utilise PostgreSQL pour persister les services. Le setup Docker/PostgreSQL est documente ici:

- `../Docs/PostgreSQL-Docker-Quickstart.md`
