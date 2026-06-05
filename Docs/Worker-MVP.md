# Worker MVP

Ce document precise le role du worker MVP dans NodeConductor.

Le worker est la partie qui execute les jobs. L'API recoit et valide les demandes, mais elle ne doit pas faire le travail long ni modifier directement l'etat operationnel d'un service.

---

## 1. Responsabilites

Le worker est responsable de :

1. prendre un job `pending` ;
2. le passer en `running` ;
3. mettre le service lie en etat transitoire (`starting` ou `stopping`) ;
4. executer l'action demandee ;
5. terminer le job en `succeeded` ou `failed` ;
6. mettre le service en `on`, `off` ou `error` ;
7. emettre les events metier decrits dans `Docs/Logs-et-evenements.md`.

Ces responsabilites restent les memes quel que soit le mode d'execution.
Le worker orchestre le cycle de vie metier; l'action concrete est deleguee a
un executor choisi par configuration.

Implementation MVP actuelle :

```text
run_job(job_id)
```

Cette fonction execute un job precis de maniere synchrone et manuelle.

Le worker repond a la question :

```text
Comment NodeConductor execute-t-il une demande deja acceptee ?
```

---

## 1.1 Modes d'execution

NodeConductor prepare deux modes worker :

```text
NODECONDUCTOR_WORKER_MODE=simulation
NODECONDUCTOR_WORKER_MODE=real
```

Le mode par defaut est :

```text
simulation
```

### `simulation`

Le mode `simulation` est le mode sur pour les demonstrations, les tests et les
environnements fictifs.

Il doit :

- utiliser sa propre instance NodeConductor ;
- utiliser sa propre base PostgreSQL ;
- ne jamais appeler Docker, Proxmox, Wake-on-LAN, SSH ou un autre outil infra ;
- reproduire le cycle de vie des jobs et des services ;
- permettre de presenter le projet sans materiel disponible sur le reseau local.

La simulation est donc un environnement complet et isole, pas une deuxieme base
cachee dans une instance reelle.

### `real`

Le mode `real` est le futur mode d'execution reelle.

Dans l'etat actuel, il est volontairement prepare mais non branche :

- aucun appel Docker ;
- aucun appel Proxmox ;
- aucun paquet Wake-on-LAN ;
- aucun acces reseau infra.

Un job execute en mode `real` echoue proprement avec un message explicite tant
que les connecteurs reels ne sont pas implementes.

Le code Wake-on-LAN existant dans `Bot-CubeGuardian` sert de reference future
pour concevoir un connecteur isole. Il n'est pas copie ni appele par
NodeConductor dans cette etape.

---

## 2. Limites

Le worker ne decide pas si une action peut etre demandee.

Cette responsabilite reste cote API et services metier :

- verifier que le service existe ;
- verifier qu'il n'y a pas d'action contradictoire ;
- creer le job ;
- renvoyer rapidement une reponse HTTP.

Le worker ne doit pas etre appele directement par un frontend, un bot Discord ou un LLM. Ces clients passent par l'API.

Dans le MVP, le worker ne pilote pas encore :

- Proxmox ;
- Docker ;
- Wake-on-LAN ;
- SSH ;
- IPMI ;
- notifications reelles.

Il simule l'execution pour stabiliser le cycle de vie des jobs.

---

## 3. Cycle de vie

Cycle nominal :

```text
pending
  -> running
  -> succeeded
```

Cycle en erreur :

```text
pending
  -> running
  -> failed
```

Transitions de service :

```text
start: off -> starting -> on
stop: on -> stopping -> off
failure: starting/stopping -> error
```

Un job deja `running`, `succeeded`, `failed` ou `cancelled` ne doit pas etre repris comme un job `pending`.

---

## 4. Regles de securite

Regles MVP :

- le worker prend uniquement des jobs `pending` ;
- il ne traite qu'un job a la fois ;
- il ne lance aucune action infra reelle ;
- il met le job en `failed` si l'execution echoue ;
- il met le service en `error` si le resultat est `failed` ;
- il conserve `error_message` quand un echec est fourni ;
- il ne logue aucun secret ;
- il ne masque pas les erreurs en success.

Regles futures :

- timeouts par etape ;
- retries controles ;
- annulation cooperative d'un job `running` ;
- verrou par service si plusieurs workers existent ;
- events metier a chaque etape importante.

---

## 5. `simulate-complete`

L'endpoint `POST /api/v1/jobs/{job_id}/simulate-complete` reste un outil de developpement et de demo.

Dans le MVP, il appelle la meme logique que le worker manuel :

```text
simulate-complete -> run_simulated_job -> run_job
```

Cela evite deux implementations differentes :

```text
API simulate-complete -> worker MVP -> repository jobs/services
```

Quand un vrai worker automatique existera, cet endpoint pourra etre garde pour les tests, limite aux environnements de dev, ou retire.

---

## 6. Lien avec les events

Les jobs portent l'etat d'execution.

Les events portent l'historique consultable :

- job demande ;
- job pris par le worker ;
- status service change ;
- job reussi ;
- job echoue ;
- job annule ;
- action refusee.

Le worker cree les events metier principaux. Les details techniques fins
resteront reserves au mode debug pour ne pas rendre l'historique normal trop
bruyant.

---

## 7. Decoupage de developpement

Etat actuel :

- la documentation worker et les regles de code sont posees ;
- la logique worker est separee dans un module dedie ;
- le repository possede une fonction explicite pour claim un job `pending` ;
- `run_job` permet une execution manuelle testable ;
- `simulate-complete` reste une facade de developpement/demo ;
- `run_next_pending_job` execute au plus un job `pending` ;
- une boucle automatique peut etre activee par configuration.

Configuration de la boucle automatique :

```text
NODECONDUCTOR_WORKER_AUTO_ENABLED=false
NODECONDUCTOR_WORKER_POLL_INTERVAL_SECONDS=5
```

Par defaut, la boucle automatique est desactivee.

Quand elle est activee, elle :

- traite au plus un job par cycle ;
- attend l'intervalle configure entre deux cycles ;
- ne cherche pas a etre instantanee ;
- evite une boucle rapide inutilement consommatrice.

Prochaines etapes possibles :

1. ajouter une commande interne ou un endpoint admin reserve pour declencher un job ;
2. brancher progressivement les connecteurs infra ;
3. ajouter un mode debug configurable pour les events ;
4. ajouter une strategie d'archivage des jobs/events.

---

## 8. Ce qu'on ne fait pas tout de suite

On ne met pas encore :

- worker dans un process separe ;
- Celery ;
- Redis ;
- RabbitMQ ;
- vraie integration infra ;
- mode debug persistant ;
- archivage automatique.

Le but est de stabiliser le coeur metier avant d'ajouter des mecanismes plus lourds.
