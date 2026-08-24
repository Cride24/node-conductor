# API v1 - Endpoints actuels et cibles

Ce document decrit l'API v1 de NodeConductor.

Important : les endpoints de jobs sont une simulation MVP. Ils creent et font evoluer des jobs en base, mais ne pilotent pas encore Proxmox, Docker ou Wake-on-LAN.

Note : l'historique d'activite et les events sont documentes dans [`Logs-et-evenements.md`](Logs-et-evenements.md).

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
- **Parametres query** :
  - `limit`, entre `1` et `200`, defaut `50` ;
  - `offset`, superieur ou egal a `0`, defaut `0`.
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
  "warnings": [],
  "limit": 50,
  "offset": 0
}
```

`total` correspond au nombre total de services en base. `valid_count` et
`invalid_count` concernent uniquement la page demandee.

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
  - `dependencies`
  - `device_dependencies`
- **Champ volontairement non modifiable** :
  - `status` : l'etat d'un service doit correspondre a son etat reel ou simule, et sera modifie par les actions metier (`start`, `stop`, jobs), pas par le PATCH general.

- **Exemple de requete** :

```json
{
  "description": "serveur minecraft steampunk mis a jour"
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
  "status": "off",
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

- **But** : demander le demarrage ou l'arret d'un service.
- **Principe** : l'API ne doit pas executer directement l'action longue. Elle valide la demande, cree un job en base, laisse le `status` du service intact, puis renvoie rapidement le `job_id`. Le worker, ou l'endpoint de simulation MVP, est responsable de passer le service en `starting`, `stopping`, `on`, `off`, `error` ou `unknown`.
- **Atomicite** : la verification du job actif et la creation sont executees
  dans une transaction PostgreSQL verrouillant le service. Le job conserve le
  `target_id` connu lors de sa creation.
- **Methode** : `POST`
- **URL** :
  - `/api/v1/services/{service_id}/start`
  - `/api/v1/services/{service_id}/stop`
- **Entree** :
  - `service_id` dans l'URL ;
  - source de la demande a tracer progressivement : `web`, `discord`, `llm`, `system`, `unknown`.
- **Reponse 202 (Accepted)** si la demande est acceptee :

```json
{
  "job_id": 42,
  "service_id": 1,
  "action": "start",
  "job_status": "pending",
  "service_status": "off"
}
```

- **Reponse 200 (OK)** si la demande est deja satisfaite ou deja en cours dans le meme sens :

```json
{
  "job_id": 42,
  "service_id": 1,
  "action": "start",
  "job_status": "pending",
  "service_status": "off",
  "message": "Service start is already requested"
}
```

- **409 (Conflict)** si l'etat actuel rend l'action contradictoire :

```json
{
  "detail": "Service 1 already has an active stop job"
}
```

- **404 (Not Found)** si le service n'existe pas :

```json
{
  "detail": "Service not found"
}
```

- **Regle MVP** : une seule action active par service. Une demande identique a l'action active peut renvoyer `200 OK`; une demande contradictoire renvoie `409 Conflict`. Le `status` du service n'est pas modifie par la creation du job.
- **Detail de conception** : voir [`Jobs-et-actions.md`](Jobs-et-actions.md).

---

## 1.8. POST /api/v1/jobs/{job_id}/cancel

- **But** : annuler un job qui n'a pas encore commence.
- **Methode** : `POST`
- **URL** : `/api/v1/jobs/{job_id}/cancel`
- **Entree** :
  - `job_id` dans l'URL.
- **Reponse 200 (OK)** si le job est annule ou deja annule :

```json
{
  "id": 42,
  "service_id": 1,
  "target_id": null,
  "operation_id": null,
  "action": "start",
  "status": "cancelled",
  "requested_by_type": "unknown",
  "requested_by_id": null,
  "created_at": "2026-05-30T15:10:00Z",
  "started_at": null,
  "finished_at": "2026-05-30T15:11:00Z",
  "error_message": null,
  "queue_duration_ms": null,
  "execution_duration_ms": null,
  "verification_duration_ms": null,
  "total_duration_ms": null
}
```

- **409 (Conflict)** si le job ne peut pas etre annule :

```json
{
  "detail": "Job 42 is already running and cannot be cancelled yet"
}
```

- **404 (Not Found)** si le job n'existe pas :

```json
{
  "detail": "Job not found"
}
```

- **Regle MVP** : seuls les jobs `pending` sont annulables. Les jobs `running`,
  `succeeded`, `failed` et `indeterminate` renvoient `409 Conflict`.
- **Effet sur le service** : aucun changement de `services.status`. Un job `pending` n'a pas encore ete pris par le worker, donc annuler ce job annule seulement la demande.

---

## 1.9. GET /api/v1/jobs/{job_id}

- **But** : consulter le detail d'un job.
- **Methode** : `GET`
- **URL** : `/api/v1/jobs/{job_id}`
- **Entree** :
  - `job_id` dans l'URL.
- **Reponse 200 (OK)** :

```json
{
  "id": 42,
  "service_id": 1,
  "target_id": null,
  "operation_id": null,
  "action": "start",
  "status": "pending",
  "requested_by_type": "llm",
  "requested_by_id": "agent-1",
  "created_at": "2026-05-30T15:10:00Z",
  "started_at": null,
  "finished_at": null,
  "error_message": null,
  "queue_duration_ms": null,
  "execution_duration_ms": null,
  "verification_duration_ms": null,
  "total_duration_ms": null
}
```

- **404 (Not Found)** si le job n'existe pas :

```json
{
  "detail": "Job not found"
}
```

---

## 1.10. POST /api/v1/jobs/{job_id}/simulate-complete

- **But** : simuler la fin d'un job sans connecter encore Proxmox, Docker ou Wake-on-LAN.
- **Role actuel** : endpoint de developpement/demo. Il appelle le worker MVP manuel, mais ne remplace pas un futur worker automatique.
- **Methode** : `POST`
- **URL** : `/api/v1/jobs/{job_id}/simulate-complete`
- **Entree** :

```json
{
  "result": "succeeded",
  "error_message": null
}
```

`result` accepte `succeeded`, `failed` ou `indeterminate`.

- **Reponse 200 (OK)** :

```json
{
  "id": 42,
  "service_id": 1,
  "target_id": null,
  "operation_id": "4ba0c688-402c-4ecf-b130-60c9b893afb7",
  "action": "start",
  "status": "succeeded",
  "requested_by_type": "unknown",
  "requested_by_id": null,
  "created_at": "2026-05-30T15:10:00Z",
  "started_at": "2026-05-30T15:11:00Z",
  "finished_at": "2026-05-30T15:11:01Z",
  "error_message": null,
  "queue_duration_ms": null,
  "execution_duration_ms": null,
  "verification_duration_ms": null,
  "total_duration_ms": null
}
```

- **Effet simule** :
  - job `start` pris en charge : service `off -> starting`, puis `on` si le job reussit ;
  - job `stop` pris en charge : service `on -> stopping`, puis `off` si le job reussit ;
  - job echoue : service `error` ;
  - job `indeterminate` : service `unknown`.

Les quatre durees sont exposees comme champs nullables mais ne sont pas encore
calculees. Les connexions Agent et les cibles n'ont aucun endpoint public.

`operation_id` vaut `null` tant que le job est `pending`. Le premier claim lui
attribue un UUID stable, reutilisable par le futur Agent pour rendre une commande
idempotente. Cet identifiant n'est pas regenere pendant l'execution du job.

Le lot 3B ajoute seulement une facade interne de synchronisation read-only. Les
references de credentials restent en PostgreSQL et les chemins de certificat
sont resolus depuis la configuration externe du processus ; aucun de ces champs
n'est expose par l'API publique.

Le lot 4A fait evoluer ce contrat interne vers `api_version=v2` et la
capacite obligatoire `resource_inventory_v1`. Le Controller charge
`GET /api/v2/resources` avec `limit`, `offset` et, apres la premiere
page, le `snapshot_id` retourne. Les ressources operationnelles portent
`target_kind=compose_project|standalone_container`. Les membres Compose sont
imbriques pour observation uniquement ; une ressource ambigue porte
`target_kind=null` et `operable=false`.

Les endpoints internes v1 `/containers` restent disponibles pendant la
transition, mais seulement pour les conteneurs autonomes. Ils ne constituent
pas une API publique du Controller. Aucun endpoint de ce lot n'execute
`start`, `stop` ou une autre mutation Docker.

Le lot 4B ajoute ensuite, uniquement sur l'API interne de l'Agent :

```text
POST /api/v2/resources/{target_kind}/{target}/actions
```

Le corps strict porte `operation_id`, `actor` et `action=start|stop`. Le
resultat Agent vaut `completed`, `rejected`, `failed` ou `indeterminate` et ne
retourne qu'un etat Docker filtre. Le Controller public et son worker ne sont
pas encore branches sur cet endpoint : aucune route de ce document ne permet
donc de declencher cette mutation. Les chemins/arguments Compose restent une
configuration locale de l'Agent et ne figurent dans aucun contrat Controller.

Le worker automatique peut executer plusieurs cibles en parallele avec les
limites configurees, mais `simulate-complete` reste une facade manuelle portant
sur un seul `job_id`.

- **409 (Conflict)** si le job est deja termine ou annule.

---

## 1.11. GET /api/v1/events

- **But** : consulter l'historique metier recent de NodeConductor.
- **Methode** : `GET`
- **URL** : `/api/v1/events`
- **Filtres optionnels** :
  - `service_id`
  - `job_id`
  - `limit`, entre `1` et `200`, defaut `50`
- **Reponse 200 (OK)** :

```json
{
  "total": 1,
  "events": [
    {
      "id": 1,
      "event_type": "job.requested",
      "severity": "info",
      "message": "Start requested for service 1",
      "service_id": 1,
      "job_id": 1,
      "actor_type": "llm",
      "actor_id": "agent-1",
      "created_at": "2026-05-31T15:11:00Z",
      "details": {
        "action": "start"
      }
    }
  ]
}
```

- **Events MVP produits actuellement** :
  - `service.created`
  - `service.updated`
  - `job.requested`
  - `job.started`
  - `job.succeeded`
  - `job.failed`
  - `job.cancelled`
  - `action.rejected`
  - `service.status_changed`
