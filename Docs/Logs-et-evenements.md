# Logs et evenements

Ce document precise la conception cible pour l'historique d'activite dans NodeConductor.

L'objectif est de separer clairement :

- l'etat courant du systeme ;
- les demandes d'action ;
- l'historique de ce qui s'est passe.

Cette separation permet de surveiller le systeme, diagnostiquer les problemes et garder une trace exploitable meme si les jobs termines sont plus tard archives ou supprimes.

---

## 1. Les trois notions a ne pas melanger

### `services`

La table `services` represente l'etat courant connu de NodeConductor.

Exemples :

```text
service steampunk: status = off
service stefano: status = on
```

Un service repond a la question :

```text
Dans quel etat est cette ressource logique maintenant ?
```

### `jobs`

La table `jobs` represente les demandes d'action.

Exemples :

```text
job 42: start steampunk, pending
job 43: stop stefano, succeeded
```

Un job repond a la question :

```text
Quelle action a ete demandee, et ou en est son execution ?
```

Les jobs actifs (`pending`, `running`) servent aussi a eviter les actions contradictoires.

### `events`

La table `events` represente l'historique metier durable.

Exemples :

```text
service.created
service.updated
job.requested
job.started
job.succeeded
job.failed
service.status_changed
action.rejected
```

Un event repond a la question :

```text
Qu'est-ce qui s'est passe, quand, par qui, et avec quel contexte ?
```

---

## 2. Pourquoi separer jobs et events ?

Un job est un objet de travail.

Il doit rester simple, lisible et utile au worker :

- action demandee ;
- status courant ;
- source de la demande ;
- dates principales ;
- erreur finale eventuelle.

Un event est une trace historique.

Il peut etre plus nombreux, plus descriptif et plus adapte a l'UI, a l'audit et a la surveillance.

Cette separation permet plus tard de :

- garder seulement les jobs recents ou actifs ;
- archiver ou supprimer les jobs termines ;
- conserver l'historique metier important dans `events` ;
- afficher une timeline claire a un utilisateur, un bot Discord ou un LLM.

---

## 3. Mode normal

En mode normal, NodeConductor doit persister les evenements metier importants, sans etre trop bruyant.

Exemples d'evenements a garder :

- creation d'un service ;
- edition d'un service ;
- suppression d'un service ;
- demande de job `start` ou `stop` ;
- job demarre ;
- job reussi ;
- job echoue ;
- job annule ;
- action refusee pour conflit ;
- changement de status d'un service ;
- erreur orchestrateur ou worker.

Les events metier doivent rester tracables meme quand les details techniques
sont masques. Pour une demande de job, l'historique conserve donc toujours :

- `requested_by_type` via `actor_type` ;
- `requested_by_id` via `actor_id` ;
- le service concerne ;
- le job concerne ;
- l'action demandee ;
- le resultat final.

Le mode normal vise :

- l'historique consultable dans l'UI ;
- la surveillance du systeme ;
- l'audit des actions ;
- la comprehension rapide d'un incident.

---

## 4. Mode debug configurable

Le mode debug ajoute des traces plus fines, mais il ne doit pas etre actif en permanence.

Il pourra etre controle plus tard par configuration, par exemple :

```text
NODECONDUCTOR_EVENT_LEVEL=info
NODECONDUCTOR_EVENT_LEVEL=debug
```

En mode debug, NodeConductor pourra ajouter :

- validation de demande commencee ;
- validation de demande terminee ;
- worker a pris un job ;
- verification de dependances ;
- appel connecteur commence ;
- appel connecteur termine ;
- timeout detecte ;
- retry programme ;
- details d'erreur utiles au diagnostic.

Les details techniques du worker appartiennent a ce mode debug :

- mode worker utilise ;
- executor selectionne ;
- connecteur futur (`docker`, `proxmox`, `wake_on_lan`, etc.) ;
- methode employee par un connecteur ;
- duree detaillee d'une etape ;
- erreur technique non sensible.

Regles importantes :

- ne jamais stocker de secret ;
- ne pas exposer de token, mot de passe, cle API ou URL sensible complete ;
- garder les messages comprehensibles par un humain ;
- garder les details techniques dans `details` plutot que dans un message trop long ;
- pouvoir desactiver ce bruit en production.

Les logs techniques tres fins pourront aussi aller vers stdout ou des fichiers. La base doit d'abord garder les events utiles a l'historique metier.

---

## 5. Modele cible de table `events`

Proposition minimale :

```text
events
- id
- event_type
- severity
- message
- service_id nullable
- job_id nullable
- actor_type
- actor_id nullable
- created_at
- details json nullable
```

### `event_type`

Type machine-readable de l'evenement.

Exemples :

```text
service.created
service.updated
service.deleted
job.requested
job.started
job.succeeded
job.failed
job.cancelled
action.rejected
service.status_changed
orchestrator.error
worker.error
```

### `severity`

Niveau de gravite :

```text
info
warning
error
debug
```

Sens propose :

| Severity | Usage |
|---|---|
| `info` | activite normale importante |
| `warning` | situation anormale mais controlee |
| `error` | echec ou incident a diagnostiquer |
| `debug` | trace detaillee activee par configuration |

### `message`

Phrase courte et lisible par un humain.

Exemples :

```text
Service steampunk created
Start requested for service steampunk
Job 42 succeeded
Stop rejected: service already has an active start job
```

### `service_id` et `job_id`

Ces champs permettent de filtrer l'historique :

- par service ;
- par job ;
- dans une timeline globale.

Ils sont nullable car certains evenements concernent l'orchestrateur lui-meme, le bot Discord, ou un futur connecteur.

### `actor_type` et `actor_id`

Ils indiquent qui est a l'origine de l'action :

```text
web
discord
llm
system
unknown
```

`actor_id` dependra de la source :

- id utilisateur web ;
- id utilisateur Discord ;
- id technique d'un agent ou LLM ;
- `null` si inconnu dans le MVP.

### `details`

Champ JSON pour le contexte structure.

Exemples :

```json
{
  "old_status": "off",
  "new_status": "starting"
}
```

```json
{
  "reason": "active_job_conflict",
  "active_job_id": 42,
  "active_action": "start"
}
```

---

## 6. Consultation par UI, Discord ou LLM

La future API pourra exposer une liste d'evenements filtrable.

Exemples de filtres cibles :

- derniers evenements globaux ;
- evenements d'un service ;
- evenements d'un job ;
- severite minimum ;
- type d'evenement ;
- periode ;
- acteur.

Objectif UI :

- afficher une timeline claire ;
- donner une vision rapide des incidents ;
- permettre de comprendre pourquoi une action a ete refusee ou a echoue.

Objectif Discord :

- pouvoir repondre a une commande du type "que s'est-il passe ?" ;
- afficher les derniers evenements importants d'un service.

Objectif LLM :

- donner un contexte fiable a l'assistant ;
- lui permettre de diagnostiquer sans deviner ;
- eviter qu'il confonde etat courant, demande active et historique.

---

## 7. Archivage et retention

Les jobs termines pourront devenir nombreux.

Strategie cible :

1. garder les jobs actifs et recents en base principale ;
2. archiver ou supprimer les vieux jobs termines selon une politique configurable ;
3. conserver les events metier importants plus longtemps ;
4. eventuellement archiver aussi les events anciens dans une table ou un fichier dedie.

Cette strategie n'est possible que si les events contiennent l'historique important.

Regle cle :

```text
Supprimer un vieux job ne doit pas supprimer l'histoire utile de ce qui s'est passe.
```

---

## 8. MVP implemente

Le MVP actuel contient :

- une table `events` ;
- un repository events ;
- un service d'enregistrement et de lecture ;
- l'endpoint `GET /api/v1/events` ;
- les filtres `service_id`, `job_id` et `limit` ;
- des events produits par les services, jobs et worker MVP.

Les events sont crees pour :

- creation de service ;
- edition de service ;
- demande de job ;
- annulation de job ;
- conflit refuse ;
- job pris par le worker ;
- job reussi ;
- job echoue ;
- changement de status service.

Le demarrage de l'application peut aussi produire un event systeme rare :

```text
system.started
```

Cet event permet de lire le mode de l'instance sans polluer chaque event metier.
Ses details contiennent notamment :

```json
{
  "worker_mode": "simulation",
  "event_level": "info",
  "worker_auto_enabled": false
}
```

Le mode worker n'est pas ajoute a chaque event metier en mode normal. Si ce
detail devient necessaire pour diagnostiquer un job, il sera expose par les
events ou details de debug.

---

## 9. Ce qu'on ne code pas maintenant

On garde volontairement une portee limitee. On ne cree pas encore :

- configuration de niveau debug ;
- mecanisme d'archivage ;
- integration avec un systeme externe de logs.

Le mode debug persistant viendra plus tard.

---

## 10. Liens avec les autres docs

- `Docs/Jobs-et-actions.md` : explique les jobs, les transitions et le worker.
- `Docs/API-v1.md` : decrit l'endpoint public de consultation des events.
- `Docs/Cahier-des-charges.md` : pose le besoin global de logs structures et d'historique consultable.
