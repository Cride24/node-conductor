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
- `GET /api/v1/services`
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

### PostgreSQL local

Le backend utilise PostgreSQL pour persister les services. Le setup Docker/PostgreSQL est documente ici:

- `../Docs/PostgreSQL-Docker-Quickstart.md`
