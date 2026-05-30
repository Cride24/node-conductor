# API v1 - Endpoints actuels et cibles

Ce document decrit l'API v1 de NodeConductor.

Important :

- les endpoints `health`, `version`, `services` et `PATCH services` existent dans le backend actuel ;
- les endpoints `start` / `stop` sont documentes comme conception cible, mais ne sont pas encore implementes.

---

## 1.1. GET /api/v1/health

- **But** : connaitre l'etat global simplifie de l'orchestrateur.
- **Methode** : `GET`
- **URL** : `/api/v1/health`
- **Entree** : rien pour l'instant.
- **Reponse 200 (OK)** :

```json
{
  "status": "OK",
  "process_started_at": 1780083356.0934246,
  "process_uptime_seconds": 42
}
```

---

## 1.2. GET /api/v1/version

- **But** : connaitre le nom de l'application et les versions exposees par le backend.
- **Methode** : `GET`
- **URL** : `/api/v1/version`
- **Entree** : rien.
- **Reponse 200 (OK)** :

```json
{
  "name": "NodeConductor",
  "app_version": "0.1.0",
  "api_version": "0.1.1"
}
```

---

## 1.3. GET /api/v1/services

- **But** : lister les services connus par l'orchestrateur.
- **Methode** : `GET`
- **URL** : `/api/v1/services`
- **Entree** : rien.
- **Stockage actuel** : PostgreSQL via le repository `services_repository.py`.
- **Reponse 200 (OK)** :

```json
{
  "total": 2,
  "valid_count": 2,
  "services": [
    {
      "id": 1,
      "name": "steampunk",
      "type": "LXC",
      "category": "game",
      "description": "serveur minecraft sur le theme steampunk",
      "status": "off",
      "dependencies": null,
      "device_dependencies": null
    },
    {
      "id": 2,
      "name": "stefano",
      "type": "VM",
      "category": "tool",
      "description": "outil de developpement pour le projet stefano",
      "status": "on",
      "dependencies": null,
      "device_dependencies": null
    }
  ],
  "invalid_count": 0,
  "warnings": []
}
```

---

## 1.4. GET /api/v1/services/{service_id}

- **But** : obtenir le detail d'un service.
- **Methode** : `GET`
- **URL** : `/api/v1/services/{service_id}`
- **Entree** :
  - `service_id` dans l'URL, sous forme d'identifiant numerique.
- **Reponse 200 (OK)** :

```json
{
  "id": 1,
  "name": "steampunk",
  "type": "LXC",
  "category": "game",
  "description": "serveur minecraft sur le theme steampunk",
  "status": "off",
  "dependencies": null,
  "device_dependencies": null
}
```

- **404 (Not Found)** si le service n'existe pas :

```json
{
  "detail": "Service not found"
}
```

---

## 1.5. POST /api/v1/services/

- **But** : creer un service.
- **Methode** : `POST`
- **URL** : `/api/v1/services/`
- **Entree** :

```json
{
  "name": "forge",
  "type": "LXC",
  "category": "game",
  "description": "instance minecraft forge",
  "dependencies": [1],
  "device_dependencies": null
}
```

- **Reponse 201 (Created)** :

```json
{
  "id": 3,
  "name": "forge",
  "type": "LXC",
  "category": "game",
  "description": "instance minecraft forge",
  "status": "off",
  "dependencies": [1],
  "device_dependencies": null
}
```

- **409 (Conflict)** si le nom existe deja :

```json
{
  "detail": "Service with name forge already exists"
}
```

---

## 1.6. PATCH /api/v1/services/{service_id}

- **But** : modifier partiellement un service existant.
- **Methode** : `PATCH`
- **URL** : `/api/v1/services/{service_id}`
- **Entree** :
  - `service_id` dans l'URL ;
  - un JSON contenant au moins un champ a modifier.
- **Champs modifiables actuellement** :
  - `name`
  - `type`
  - `category`
  - `description`
  - `status`
  - `dependencies`
  - `device_dependencies`

- **Exemple de requete** :

```json
{
  "description": "serveur minecraft steampunk mis a jour",
  "status": "starting"
}
```

- **Reponse 200 (OK)** si la mise a jour reussit :

```json
{
  "id": 1,
  "name": "steampunk",
  "type": "LXC",
  "category": "game",
  "description": "serveur minecraft steampunk mis a jour",
  "status": "starting",
  "dependencies": null,
  "device_dependencies": null
}
```

- **400 (Bad Request)** si aucun champ n'est fourni :

```json
{
  "detail": "At least one field must be provided"
}
```

- **404 (Not Found)** si le service n'existe pas :

```json
{
  "detail": "Service not found"
}
```

- **409 (Conflict)** si le nouveau nom existe deja :

```json
{
  "detail": "Service with name stefano already exists"
}
```

---

## 1.7. POST /api/v1/services/{service_id}/start|stop

Etat : **conception cible, pas encore implemente dans le backend**.

- **But** : demander le demarrage ou l'arret d'un service.
- **Principe** : l'API ne doit pas executer directement l'action longue. Elle valide la demande, cree un job en base, met le service dans un etat transitoire (`starting` ou `stopping`), puis renvoie rapidement le `job_id`.
- **Methode** : `POST`
- **URL** :
  - `/api/v1/services/{service_id}/start`
  - `/api/v1/services/{service_id}/stop`
- **Entree** :
  - `service_id` dans l'URL ;
  - source de la demande a tracer progressivement : `web`, `discord`, `llm`, `system`, `unknown`.
- **Reponse cible 202 (Accepted)** si la demande est acceptee :

```json
{
  "job_id": 42,
  "service_id": 1,
  "action": "start",
  "job_status": "pending",
  "service_status": "starting"
}
```

- **Reponse cible 200 (OK)** si la demande est deja satisfaite ou deja en cours dans le meme sens :

```json
{
  "service_id": 1,
  "action": "start",
  "service_status": "starting",
  "message": "Service start is already in progress"
}
```

- **409 (Conflict)** si l'etat actuel rend l'action contradictoire :

```json
{
  "detail": "Service 1 is currently stopping"
}
```

- **404 (Not Found)** si le service n'existe pas :

```json
{
  "detail": "Service not found"
}
```

- **Regle MVP** : une seule action active par service. Une demande identique a l'action en cours peut renvoyer `200 OK`; une demande contradictoire renvoie `409 Conflict`.
- **Detail de conception** : voir [`Jobs-et-actions.md`](Jobs-et-actions.md).
