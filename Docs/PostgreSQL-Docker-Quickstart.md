# PostgreSQL + Docker (premiere etape)

Objectif: lancer une base locale pour preparer la migration du repository memoire vers SQL.

## 1) Lancer PostgreSQL

Depuis la racine `NodeConductor`:

```powershell
docker compose up -d
```

## 2) Verifier que le conteneur tourne

```powershell
docker ps --filter "name=nodeconductor-postgres"
```

## 3) Ouvrir psql dans le conteneur

```powershell
docker exec -it nodeconductor-postgres psql -U nodeconductor -d nodeconductor
```

## 4) Requete de verification

```sql
SELECT id, name, status
FROM services
ORDER BY id;
```

## 5) Arreter l'environnement

```powershell
docker compose down
```

## Notes architecture

- Aujourd'hui, `repository/services_repository.py` reste en memoire.
- La prochaine marche sera d'ajouter une implementation SQL dans la couche repository.
- Les couches route et service doivent bouger le moins possible pendant cette migration.
