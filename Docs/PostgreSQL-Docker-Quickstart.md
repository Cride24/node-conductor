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

- `backend/src/nodeconductor/repositories/services_repository.py` utilise maintenant PostgreSQL pour lire, creer et modifier les services.
- Les routes et services metier gardent des signatures simples pour eviter de coupler l'API HTTP aux details SQL.
- Les tests utilisent `reset_rows()` pour remettre la table `services` dans un etat connu avant chaque scenario.

## Worker automatique

Le worker automatique est desactive par defaut. Pour l'activer en local :

```powershell
$env:NODECONDUCTOR_WORKER_AUTO_ENABLED="true"
$env:NODECONDUCTOR_WORKER_POLL_INTERVAL_SECONDS="5"
```

L'intervalle reste volontairement calme : le worker traite au plus un job par cycle et attend entre deux passages.
