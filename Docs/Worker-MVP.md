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
7. plus tard, emettre les events metier decrits dans `Docs/Logs-et-evenements.md`.

Implementation MVP actuelle :

```text
run_job(job_id, result="succeeded", error_message=None)
```

Cette fonction execute un job precis de maniere synchrone et manuelle.

Le worker repond a la question :

```text
Comment NodeConductor execute-t-il une demande deja acceptee ?
```

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

Les futurs events porteront l'historique consultable :

- job demande ;
- job pris par le worker ;
- status service change ;
- job reussi ;
- job echoue ;
- job annule ;
- action refusee.

Le worker MVP ne cree pas encore d'events, mais son decoupage doit permettre de les ajouter sans reecrire toute l'execution.

---

## 7. Decoupage de developpement

Etat actuel :

- la documentation worker et les regles de code sont posees ;
- la logique worker est separee dans un module dedie ;
- le repository possede une fonction explicite pour claim un job `pending` ;
- `run_job` permet une execution manuelle testable ;
- `simulate-complete` reste une facade de developpement/demo.

Prochaines etapes possibles :

1. ajouter les events metier ;
2. ajouter une commande interne ou un endpoint admin reserve pour declencher un job ;
3. ajouter une boucle worker automatique ;
4. brancher progressivement les connecteurs infra.

---

## 8. Ce qu'on ne fait pas tout de suite

On ne met pas encore :

- boucle permanente ;
- thread ou process separe ;
- Celery ;
- Redis ;
- RabbitMQ ;
- vraie integration infra ;
- table `events` ;
- endpoints events.

Le but est de stabiliser le coeur metier avant d'ajouter des mecanismes plus lourds.
