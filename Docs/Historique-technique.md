# Historique technique

Ce document sert de fil de lecture pour comprendre la progression technique de NodeConductor.

Il ne remplace pas le `git log`, mais il donne le sens des etapes : pourquoi les changements ont ete faits, dans quel ordre, et quelle branche contient quoi.

---

## 1. Socle initial

Point de depart actuel :

- API FastAPI minimale ;
- endpoints `health` et `version` ;
- premiers endpoints services ;
- documentation de vision dans `README.md` et `Docs/Cahier-des-charges.md`.

Branche repere :

```text
master / feature/health
```

Objectif :

```text
poser le squelette API et la vision generale du projet.
```

---

## 2. Passage des services vers PostgreSQL

Le repository services a ete migre vers PostgreSQL.

Changements importants :

- table `services` ;
- donnees seed `steampunk` et `stefano` ;
- helper `reset_rows()` pour isoler les tests ;
- quickstart PostgreSQL + Docker.

Branche repere :

```text
feature/services-in-memory
docs/postgres-quickstart-cleanup
```

Objectif :

```text
sortir du stockage memoire et commencer une base persistante locale.
```

---

## 3. Edition des services

Ajout du endpoint PATCH pour modifier un service.

Decision importante :

```text
PATCH ne peut pas modifier services.status.
```

Raison :

- `status` doit representer l'etat reel ou simule ;
- il ne doit pas devenir une simple valeur editable par l'utilisateur ;
- les actions metier et le worker sont proprietaires de cette transition.

Branche repere :

```text
feature/update-service-endpoint
```

Objectif :

```text
permettre l'edition des metadonnees service sans casser le modele d'etat.
```

---

## 4. Conception start / stop / jobs

Avant de piloter une infrastructure reelle, le projet a pose un modele de jobs.

Documents importants :

- `Docs/Jobs-et-actions.md`
- `Docs/API-v1.md`

Decisions importantes :

- une demande `start` ou `stop` cree un job ;
- l'API repond vite avec un `job_id` ;
- une seule action active par service ;
- une demande identique peut etre idempotente ;
- une demande contradictoire renvoie `409 Conflict`.

Branche repere :

```text
feature/start-stop-jobs-design
```

Objectif :

```text
eviter qu'un frontend, un bot Discord ou un LLM puisse enchainer des actions contradictoires sans controle.
```

---

## 5. Jobs foundation

Implementation de la base jobs.

Changements importants :

- table `jobs` ;
- endpoints `start`, `stop`, `cancel`, `get job`, `simulate-complete` ;
- annulation limitee aux jobs `pending` ;
- idempotence par job actif ;
- premiers tests de flux jobs.

Decision importante :

```text
l'API de demande ne modifie pas directement services.status.
```

Le worker, ou sa simulation MVP, est responsable des transitions :

```text
start: off -> starting -> on
stop: on -> stopping -> off
failure: starting/stopping -> error
```

Branche repere :

```text
feature/jobs-foundation
```

Objectif :

```text
separer demande d'action et execution.
```

---

## 6. Documentation du code et des events

Deux besoins ont ete formalises :

1. garder le code lisible avec des commentaires courts ;
2. preparer l'historique d'activite.

Documents importants :

- `Docs/Logs-et-evenements.md`
- `Docs/Regles-de-code.md`

Decisions importantes :

- les `jobs` portent l'etat d'execution ;
- les futurs `events` portent l'historique consultable ;
- les logs debug persistants seront configurables plus tard ;
- les regles de code sont souples, inspirees de l'esprit 42.

Objectif :

```text
permettre a un humain, a un bot ou a un LLM de comprendre ce qui s'est passe sans deviner.
```

---

## 7. Worker MVP

La logique worker a ete separee du service jobs.

Documents importants :

- `Docs/Worker-MVP.md`
- `Docs/Regles-de-code.md`

Changements importants :

- module `jobs_worker.py` ;
- fonction `run_job(job_id, result="succeeded", error_message=None)` ;
- fonction `run_next_pending_job()` ;
- `simulate-complete` devient une facade de developpement/demo ;
- claim explicite d'un job `pending`.

Branche repere :

```text
feature/worker-mvp
```

Objectif :

```text
stabiliser le coeur d'execution sans encore brancher Docker, Proxmox ou Wake-on-LAN.
```

---

## 8. Events MVP et boucle worker automatique

Ajout de l'historique metier et d'une boucle worker sobre.

Changements importants :

- table `events` ;
- endpoint `GET /api/v1/events` ;
- events produits par services, jobs et worker ;
- boucle worker automatique desactivee par defaut ;
- intervalle configurable pour eviter une boucle trop rapide.

Configuration :

```text
NODECONDUCTOR_WORKER_AUTO_ENABLED=false
NODECONDUCTOR_WORKER_POLL_INTERVAL_SECONDS=5
```

Branche actuelle :

```text
feature/events-worker-loop
```

Objectif :

```text
donner une memoire au systeme avant de rendre le worker plus autonome.
```

---

## 9. Etat actuel avant la prochaine discussion

Etat du projet :

- services persistants dans PostgreSQL ;
- jobs persistants ;
- events persistants ;
- worker MVP manuel ;
- boucle worker automatique optionnelle ;
- aucune action infrastructure reelle ;
- modes `simulation` / `real` prepares dans le worker ;
- pas encore de connecteurs Docker, Proxmox ou Wake-on-LAN.

La suite logique :

```text
concevoir et implementer les modes worker simulation / real.
```

Le mode simulation devra permettre de demontrer NodeConductor sans toucher l'infrastructure reelle.

Le mode real devra etre strictement encadre avant d'appeler des connecteurs infra.

---

## 9.1 Modes worker simulation / real

Le worker a ete prepare pour distinguer deux modes d'execution :

```text
simulation
real
```

Decisions importantes :

- une instance NodeConductor utilise une seule base via `NODECONDUCTOR_DATABASE_URL` ;
- la separation simulation / reel se fait par conteneur, base, secrets et reseau ;
- `simulation` est le mode par defaut ;
- `simulation` ne declenche aucune action infrastructure reelle ;
- `real` existe comme point d'extension mais n'appelle pas encore Docker, Proxmox ou Wake-on-LAN ;
- les events metier gardent la tracabilite de l'acteur qui demande le job ;
- les details techniques du worker sont reserves au futur mode debug ;
- un event `system.started` donne le mode global de l'instance au demarrage.

Reference future :

```text
Bot-CubeGuardian contient un Wake-on-LAN fonctionnel pour le serveur G6.
```

Ce code sert de retour d'experience pour un futur connecteur WoL isole. Il
n'est pas branche dans NodeConductor a cette etape.

Objectif :

```text
preparer un worker proprement extensible sans risquer d'influencer l'infra reelle.
```

---

## 10. Branches utiles

Branches de lecture :

```text
feature/jobs-foundation
feature/worker-mvp
feature/events-worker-loop
```

Ces branches sont des reperes historiques. Les changements worker/events et les
garde-fous API ont ensuite ete fusionnes et pousses sur `master`.

---

## 11. Conception du worker reel et de l'Agent Docker

Un brainstorm d'architecture a fixe la cible avant de commencer les appels
infrastructure reels.

Decisions principales :

- Docker sera le premier connecteur reel ;
- Docker sera pilote par un Agent NodeConductor restreint installe sur l'hote ;
- l'agent inventorie tous les conteneurs sans les rendre pilotables par defaut ;
- les politiques de cible sont `discovered`, `managed` et `protected` ;
- la politique par defaut est `discovered` ;
- un succes exige l'observation de l'etat final et, si configure, de la
  disponibilite applicative ;
- le resultat `indeterminate` et l'etat `unknown` representent une incertitude ;
- la file PostgreSQL reste persistante mais devient concurrente et bornee ;
- une seule action peut etre active pour une cible
  `(driver, connection_id, target)` ;
- les durees de file, d'execution et de verification sont mesurees separement ;
- la simulation utilise des durees credibles sans alimenter les statistiques
  reelles ;
- une reconciliation est executee apres un redemarrage ;
- le pilotage du moteur Docker lui-meme est reporte tant qu'il ne peut pas etre
  teste depuis une machine independante.

La conception complete est la source de verite pour les prochains lots :

```text
Docs/Worker-reel-et-Agent-Docker.md
```

Aucune implementation de l'agent ou du driver Docker n'a ete ajoutee pendant
cette etape documentaire.

---

## 12. Contrats et modele de donnees du worker reel

Le premier lot de la conception du worker reel a ete implemente sur :

```text
feature/worker-real-contracts
```

Changements importants :

- tables `agent_connections`, `targets` et `service_targets` ;
- politique automatique `discovered` et politiques effectives
  `discovered`, `managed`, `protected` ;
- unicite PostgreSQL de `(driver, connection_id, target)` ;
- contrats des readiness checks `docker_state`, `docker_health`, `http`, `tcp` ;
- resultat `indeterminate` et etat de service `unknown` ;
- quatre colonnes de duree reservees sur les jobs, encore non calculees.

Aucun Agent Docker, driver Docker, appel reseau, appel Docker ou parallelisme
worker n'a ete ajoute dans ce lot.

---

## 13. Worker concurrent et verrouillage par cible

Le deuxieme lot du worker reel est implemente sur :

```text
feature/worker-concurrency
```

Changements importants :

- relation v1 un-a-un entre service et cible canonique ;
- snapshot nullable `jobs.target_id` pour garder la compatibilite historique ;
- index partiels interdisant plusieurs jobs actifs par service ou cible ;
- creation de job serialisee par un verrou de ligne PostgreSQL ;
- claim atomique avec `FOR UPDATE SKIP LOCKED` ;
- limites configurees a 4 jobs globaux, 2 par connexion et 1 par cible ;
- execution parallele de cibles differentes ;
- remplissage immediat des places liberees ;
- arret de la boucle sans nouveau claim et attente des jobs deja lances ;
- tests de concurrence fondes sur `Barrier` et `Event`.

L'Agent Docker, le driver Docker, les readiness checks reels, les retries, la
reconciliation et le calcul des durees restent hors de ce lot.

---

## 14. Agent Docker MVP read-only et politiques locales

Le lot 3A est implemente sur :

```text
feature/docker-agent-mvp
```

Le nouveau dossier `agent/` contient un package Python independant du backend et
de PostgreSQL. Les choix implementes sont :

- FastAPI/Uvicorn avec socket Unix par defaut ;
- HTTPS uniquement avec mTLS complet et materiel TLS valide au demarrage ;
- Docker SDK officiel isole derriere un `DockerGateway` injectable ;
- inventaire borne et strictement filtre ;
- politiques SQLite indexees par ID Docker complet ;
- `default_management_policy=discovered` ;
- audit et idempotence atomiques par `operation_id` ;
- erreurs Docker normalisees sans details de l'hote ;
- tests deterministes avec faux gateway et base temporaire ;
- test d'integration Docker limite a `list` et `inspect`, ignorable si le moteur
  n'est pas disponible.

Le developpement et les tests unitaires ont ete realises sous Windows. L'unite
`systemd` documentee est une proposition d'installation future, pas une
validation Linux. Le driver worker, les actions Docker, les readiness checks,
la synchronisation Controller et l'autorisation utilisateur restent futurs.

---

## 15. Client Controller et synchronisation read-only de l'Agent

Le lot 3B est implemente sur :

```text
feature/controller-agent-sync
```

Le Controller dispose maintenant d'un `AgentClient` injectable pour socket Unix
ou HTTPS avec mTLS obligatoire. Il verifie l'identite stable `agent_id`, la
version de contrat et les capacites avant de charger toutes les pages.

Un snapshot valide est applique atomiquement dans PostgreSQL. L'ID Docker complet
est la cible canonique ; le nom, l'etat, le health status, la politique effective,
la derniere observation et la presence sont conserves. Une cible absente d'un
snapshot complet est marquee absente sans suppression. Une reponse partielle,
invalide ou indisponible ne modifie pas l'inventaire precedent.

PostgreSQL ne conserve qu'une `credential_ref`; les chemins TLS sont resolus par
la configuration externe et ne sont pas exposes par l'API ou les events. Ce lot
n'ajoute ni endpoint public, ni planification, ni commande Docker, ni branchement
du worker.
