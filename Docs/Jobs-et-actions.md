# Jobs et actions asynchrones

Ce document precise la conception cible pour les actions de pilotage dans NodeConductor, en particulier `start`, `stop` et plus tard `restart`.

L'objectif est d'eviter qu'un client HTTP, le frontend, le bot Discord ou un LLM declenche directement une action infrastructure longue ou dangereuse.

Principe central :

```text
Une demande d'action cree un job.
Le job est ensuite execute par un worker.
```

---

## 1. Pourquoi ne pas executer directement une action ?

Une action comme "demarrer un service" peut devenir complexe :

1. verifier les droits ;
2. verifier l'etat actuel du service ;
3. allumer une machine avec Wake-on-LAN ;
4. attendre qu'elle soit joignable ;
5. demarrer des conteneurs ;
6. verifier l'etat final ;
7. notifier les utilisateurs ;
8. journaliser chaque etape.

Ce n'est pas une simple modification HTTP instantanee.

Si l'API execute tout directement dans la route `POST /start`, plusieurs problemes apparaissent :

- la requete HTTP peut durer trop longtemps ;
- deux clients peuvent demander des actions contradictoires ;
- un LLM peut envoyer plusieurs demandes sans attendre ;
- une erreur au milieu peut laisser l'etat incoherent ;
- on perd la trace precise de qui a demande quoi.

La solution est de separer la **demande** d'action et l'**execution** de l'action.

---

## 2. Flux cible

```text
Frontend / Discord bot / LLM / API externe
  -> API NodeConductor
  -> validation de la demande
  -> creation d'un job en base
  -> reponse rapide avec job_id
  -> worker
  -> execution progressive
  -> events + status final
```

L'API accepte ou refuse la demande rapidement.

Le worker fait le travail long.

---

## 3. Table `jobs`

Premiere proposition de table :

```text
jobs
- id
- service_id
- action
- status
- requested_by_type
- requested_by_id
- created_at
- started_at
- finished_at
- error_message
```

### `action`

Actions possibles au debut :

```text
start
stop
restart
```

Pour le MVP immediat, `start` et `stop` suffisent.

### `status`

Statuts possibles du job :

```text
pending
running
succeeded
failed
cancelled
```

| Status | Sens |
|---|---|
| `pending` | demande acceptee, pas encore executee |
| `running` | le worker execute le job |
| `succeeded` | action terminee avec succes |
| `failed` | action terminee en erreur |
| `cancelled` | action annulee avant execution complete |

### `requested_by_type`

Source de la demande :

```text
web
discord
llm
system
unknown
```

Ce champ est important pour la securite et l'audit.

Un LLM ne doit jamais etre une source invisible. Si une action vient du LLM, cela doit etre visible dans l'historique.

### `requested_by_id`

Identifiant du demandeur, selon la source :

- id utilisateur web ;
- id utilisateur Discord ;
- id technique pour un agent ou un LLM ;
- `null` si inconnu dans le MVP.

---

## 4. Etats des services

Les services ont leur propre etat :

```text
on
off
starting
stopping
error
```

Le job decrit l'action demandee.

Le service decrit l'etat courant ou transitoire du service.

Exemple :

```text
service steampunk: status = starting
job 42: action = start, status = running
```

---

## 5. Regles de transition simples

Pour eviter les contradictions, chaque demande doit verifier deux choses :

1. l'etat courant du service ;
2. l'existence d'un job actif (`pending` ou `running`) pour ce service.

La creation d'un job ne change pas directement le `status` du service. Le service garde son etat courant tant qu'un worker n'a pas pris le job.

La regle n'est pas seulement "accepter ou refuser". On distingue trois familles de reponses :

| Type de cas | Code HTTP | Sens |
|---|---|---|
| nouvelle action valide | `202 Accepted` | NodeConductor cree un nouveau job |
| demande deja satisfaite ou deja en cours dans le meme sens | `200 OK` | aucun nouveau job n'est cree, l'API explique l'etat courant |
| demande contradictoire ou impossible maintenant | `409 Conflict` | l'utilisateur, le bot ou le LLM doit attendre ou choisir une autre action |

Cette distinction est utile pour valider une liste d'actions proposee par un utilisateur ou un LLM : une action idempotente peut etre consideree comme non bloquante, alors qu'une action contradictoire doit etre rejetee clairement.

### Start

| Situation | Code | Resultat |
|---|---:|---|
| aucun job actif, service `off` | `202 Accepted` | creer un job `start` en `pending`, le service reste `off` |
| aucun job actif, service `on` | `200 OK` | aucun job cree, le service est deja demarre |
| job actif `start` | `200 OK` | aucun job cree, le demarrage est deja demande ou en cours |
| job actif `stop` | `409 Conflict` | refuser, une action contradictoire existe deja |
| service `starting` sans job actif | `409 Conflict` par defaut | etat incoherent ou manuel, attendre une strategie de reconciliation |
| service `stopping` sans job actif | `409 Conflict` par defaut | refuser, le service est en cours d'arret |
| service `error` | `409 Conflict` par defaut | refuser tant qu'une strategie de recuperation n'est pas definie |

### Stop

| Situation | Code | Resultat |
|---|---:|---|
| aucun job actif, service `on` | `202 Accepted` | creer un job `stop` en `pending`, le service reste `on` |
| aucun job actif, service `off` | `200 OK` | aucun job cree, le service est deja arrete |
| job actif `stop` | `200 OK` | aucun job cree, l'arret est deja demande ou en cours |
| job actif `start` | `409 Conflict` | refuser, une action contradictoire existe deja |
| service `stopping` sans job actif | `409 Conflict` par defaut | etat incoherent ou manuel, attendre une strategie de reconciliation |
| service `starting` sans job actif | `409 Conflict` par defaut | refuser, le service est en cours de demarrage |
| service `error` | `409 Conflict` par defaut | refuser tant qu'une strategie de recuperation n'est pas definie |

Pour le MVP, on choisit une regle simple :

```text
Une seule action active par service, mais une demande identique a l'action en cours peut recevoir `200 OK`.
```

Donc :

- `start` avec un job `start` actif n'est pas contradictoire : `200 OK`, demarrage deja demande ou en cours ;
- `stop` avec un job `stop` actif n'est pas contradictoire : `200 OK`, arret deja demande ou en cours ;
- `start` avec un job `stop` actif est contradictoire : `409 Conflict` ;
- `stop` avec un job `start` actif est contradictoire : `409 Conflict`.

---

## 6. Protection contre les demandes trop rapides

Cas important :

```text
LLM -> start steampunk
LLM -> stop steampunk
LLM -> start steampunk
```

Si ces demandes arrivent sans attendre le changement d'etat, NodeConductor doit rester coherent.

Protections prevues :

1. jobs actifs en base : un service ne doit pas avoir deux actions actives contradictoires ;
2. jobs en base : chaque demande acceptee est tracee ;
3. conflits HTTP : une action incompatible renvoie `409 Conflict` ;
4. source de demande : `requested_by_type = llm`, `discord`, `web`, etc. ;
5. etats transitoires : `starting` et `stopping` sont poses par le worker, pas par l'API de demande ;
6. worker unique ou verrou par service : le worker ne prend pas deux jobs actifs pour le meme service.

---

## 7. Reponse API attendue

Quand une demande est acceptee :

```json
{
  "job_id": 42,
  "service_id": 1,
  "action": "start",
  "job_status": "pending",
  "service_status": "off"
}
```

Code HTTP :

```text
202 Accepted
```

Quand une demande est refusee car l'etat ne le permet pas :

```json
{
  "detail": "Service 1 already has an active stop job"
}
```

Code HTTP :

```text
409 Conflict
```

Quand le service n'existe pas :

```text
404 Not Found
```

---

## 8. MVP implemente

Le MVP actuel ne pilote pas encore Proxmox, Docker ou Wake-on-LAN.

Il fait ceci :

### `POST /api/v1/services/{service_id}/start`

1. verifier que le service existe ;
2. verifier s'il existe deja un job actif pour ce service ;
3. si le job actif est deja un `start`, renvoyer `200 OK` avec le job existant ;
4. si le job actif est un `stop`, renvoyer `409 Conflict` ;
5. verifier que le service est `off` ;
6. creer un job `start` avec status `pending` ;
7. laisser le service en `off` ;
8. renvoyer le `job_id`.

### `POST /api/v1/services/{service_id}/stop`

1. verifier que le service existe ;
2. verifier s'il existe deja un job actif pour ce service ;
3. si le job actif est deja un `stop`, renvoyer `200 OK` avec le job existant ;
4. si le job actif est un `start`, renvoyer `409 Conflict` ;
5. verifier que le service est `on` ;
6. creer un job `stop` avec status `pending` ;
7. laisser le service en `on` ;
8. renvoyer le `job_id`.

Ce MVP permet deja de tester :

- la forme API ;
- les conflits ;
- la trace en base ;
- le futur usage par un LLM ;
- la difference entre demande et execution.

---

## 9. Worker simule et worker futur

Dans le MVP actuel, l'endpoint `POST /api/v1/jobs/{job_id}/simulate-complete` simule le travail du worker.

Le futur worker automatique sera responsable de prendre les jobs `pending`.

Flux cible :

```text
pending
  -> running
  -> succeeded
```

Ou :

```text
pending
  -> running
  -> failed
```

Le worker mettra aussi a jour le service. C'est lui qui possede les transitions de `services.status` :

```text
start: off -> starting -> on
stop: on -> stopping -> off
```

Dans le MVP, cette transition est simulee explicitement par l'endpoint `simulate-complete`, sans connecteurs infra.

---

## 10. Annulation de job

L'annulation est utile pour le frontend, le bot Discord et surtout un LLM qui pourrait proposer ou envoyer plusieurs actions.

Endpoint cible :

```http
POST /api/v1/jobs/{job_id}/cancel
```

Principe MVP :

| Etat du job | Code | Resultat |
|---|---:|---|
| `pending` | `200 OK` | le job passe a `cancelled`, le service reste inchange |
| `cancelled` | `200 OK` | aucun changement, le job est deja annule |
| `running` | `409 Conflict` | annulation non supportee dans le MVP |
| `succeeded` | `409 Conflict` | trop tard, le job est termine |
| `failed` | `409 Conflict` | trop tard, le job est termine |

Dans la premiere version, on annule uniquement les jobs qui n'ont pas encore commence. Comme l'API de demande ne modifie plus le `status` du service, annuler un job `pending` ne modifie pas non plus le service.

Annuler un job `running` est plus complexe : le worker doit cooperer, verifier regulierement si une annulation est demandee, puis arreter proprement l'action. Plus tard, on pourra ajouter un etat intermediaire :

```text
cancelling
```

Flux futur possible :

```text
running
  -> cancelling
  -> cancelled
```

Mais ce n'est pas une priorite du MVP.

Regle de securite :

> Annuler un job ne doit pas laisser l'infrastructure dans un etat ambigu. Tant que cette garantie n'est pas implementee, seuls les jobs `pending` sont annulables.

---

## 11. Ce qu'on ne fait pas tout de suite

Pour garder une progression saine, on ne met pas encore :

- Celery ;
- Redis ;
- RabbitMQ ;
- execution parallele avancee ;
- retry automatique complexe ;
- verrou distribue ;
- vraie integration Proxmox/Docker/WoL.

On commence avec PostgreSQL, une table `jobs`, des regles d'etat simples et des tests.

---

## 12. Principe de securite

Un LLM peut aider a piloter NodeConductor, mais il ne doit pas court-circuiter les protections.

Regles de conception :

- le LLM appelle l'API comme les autres clients ;
- l'API garde les validations ;
- l'API trace la source de la demande ;
- l'API refuse les transitions invalides ;
- les actions sensibles devront plus tard passer par des droits explicites ;
- les secrets ne sont jamais exposes au LLM.

Phrase cle :

> Le LLM peut proposer ou demander une action, mais NodeConductor reste l'autorite qui valide, trace et execute.
