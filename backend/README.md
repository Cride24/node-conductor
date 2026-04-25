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

### Lancer les tests

```bash
poetry run pytest
```

### Etape PostgreSQL locale

Le premier setup Docker/PostgreSQL est documente ici:

- `../Docs/PostgreSQL-Docker-Quickstart.md`

