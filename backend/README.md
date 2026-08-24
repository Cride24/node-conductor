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
NODECONDUCTOR_WORKER_MAX_CONCURRENCY=4
NODECONDUCTOR_WORKER_MAX_CONCURRENCY_PER_CONNECTION=2
NODECONDUCTOR_API_MAX_REQUEST_BODY_BYTES=65536
NODECONDUCTOR_API_REQUEST_TIMEOUT_SECONDS=10
NODECONDUCTOR_DATABASE_CONNECT_TIMEOUT_SECONDS=3
NODECONDUCTOR_DATABASE_STATEMENT_TIMEOUT_MS=5000
NODECONDUCTOR_DATABASE_LOCK_TIMEOUT_MS=2000
NODECONDUCTOR_WORKER_EXECUTION_TIMEOUT_SECONDS=30
NODECONDUCTOR_AGENT_CONNECT_TIMEOUT_SECONDS=2
NODECONDUCTOR_AGENT_RESPONSE_TIMEOUT_SECONDS=5
NODECONDUCTOR_AGENT_MAX_RESPONSE_BYTES=262144
NODECONDUCTOR_AGENT_SYNC_PAGE_SIZE=100
NODECONDUCTOR_AGENT_SYNC_MAX_PAGES=20
```

Les listes de services sont paginees (`limit` entre 1 et 200). Les corps HTTP
trop volumineux renvoient `413`, une requete API trop longue renvoie `504`, et
les operations PostgreSQL/worker disposent de leurs propres delais configurables.

Le worker automatique execute jusqu'a 4 jobs simultanes, avec au plus 2 jobs
par connexion et toujours 1 seul par cible. PostgreSQL porte les claims et les
verrous ; ces limites s'appliquent donc aussi avec plusieurs instances worker.

La limite d'execution est cooperative. Chaque executor interne recoit une
deadline monotone et doit borner chacune de ses attentes. Un executor bloque
laisse le job `running` et conserve le verrou de cible jusqu'a son retour ; le
worker ne tente jamais de tuer ou d'abandonner un thread Python. Un UUID
`operation_id` stable est persiste lors du premier claim.

`NODECONDUCTOR_WORKER_MODE` accepte :

- `simulation` : mode par defaut, sans action infrastructure reelle ;
- `real` : futur mode reel, prepare mais non branche dans le MVP actuel.

Une instance NodeConductor utilise une seule base PostgreSQL. Une demonstration
simulee doit donc avoir sa propre instance, son propre conteneur et sa propre
base fictive, separes de l'environnement reel.

### Synchronisation interne d'un Agent

Les lots 3B et 4A fournissent la facade Python interne
`synchronize_agent_inventory(connection_id)`. Aucun endpoint public ne la
declenche encore et le worker ne l'utilise pas.

La synchronisation exige l'Agent `api_version=v2` et sa capacite
`resource_inventory_v1`. Elle charge un snapshot pagine de projets Compose,
conteneurs autonomes, membres et diagnostics ambigus, puis applique l'ensemble
dans une seule transaction PostgreSQL. L'identite d'une cible Docker est
`(driver, connection_id, target_kind, target)`. Les membres Compose ne sont
jamais des cibles de service ou de job.

Une connexion PostgreSQL conserve l'`agent_id` attendu, le transport, l'endpoint
et, pour HTTPS, une simple `credential_ref`. Les chemins TLS sont resolus depuis
l'environnement du Controller :

```text
NODECONDUCTOR_AGENT_CREDENTIAL_<REF>_CERTIFICATE
NODECONDUCTOR_AGENT_CREDENTIAL_<REF>_PRIVATE_KEY
NODECONDUCTOR_AGENT_CREDENTIAL_<REF>_SERVER_CA
```

`<REF>` est la reference mise en majuscules avec les caracteres non
alphanumeriques remplaces par `_`. Aucun chemin ou certificat n'est stocke dans
PostgreSQL ni renvoye par l'API publique.

`NODECONDUCTOR_EVENT_LEVEL` accepte :

- `info` : events metier sobres et tracables ;
- `debug` : reserve aux futurs details techniques du worker et des connecteurs.

### PostgreSQL local

Le backend utilise PostgreSQL pour persister les services. Le setup Docker/PostgreSQL est documente ici:

- `../Docs/PostgreSQL-Docker-Quickstart.md`
