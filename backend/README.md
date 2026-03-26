## NodeConductor Backend

Backend FastAPI (MVP) pour le projet **NodeConductor**.

### Lancer en dev

```bash
poetry install
poetry run uvicorn nodeconductor.main:app --reload
```

### Endpoints

- `GET /health`
- `GET /version`

