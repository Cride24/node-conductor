# Worker reel et Agent Docker

Ce document fixe les decisions de conception prises avant l'implementation du
premier worker reel de NodeConductor. Il complete `Worker-MVP.md`, qui decrit
l'etat actuellement implemente, et `Jobs-et-actions.md`, qui decrit les regles
metier des jobs.

Le contenu de ce document decrit la cible complete. Les sections d'etat en fin
de document distinguent les lots deja implementes de l'Agent Docker et des
connecteurs qui restent futurs.

---

## 1. Objectifs

Le prochain worker doit :

- executer de vraies actions d'infrastructure sans exposer directement Docker ;
- conserver un mode simulation realiste et strictement isole ;
- confirmer l'etat reel d'un service avant d'annoncer un succes ;
- executer plusieurs jobs independants sans lancer deux actions sur la meme cible ;
- mesurer les temps d'attente, d'execution et de disponibilite ;
- reprendre un etat coherent apres un redemarrage ;
- rester extensible vers Proxmox et Wake-on-LAN.

Le premier connecteur reel sera Docker.

---

## 2. Architecture Controller / Agent

NodeConductor ne doit pas recevoir un acces direct et general au socket Docker.
Chaque hote Docker pilotable possede un petit **NodeConductor Agent** installe
comme service systeme, par exemple avec `systemd` sous Linux.

```text
NodeConductor Controller
        |
        | socket Unix local ou HTTPS avec mTLS
        v
NodeConductor Agent
        |
        | acces local au moteur Docker
        v
Docker Engine
```

L'agent ne doit pas dependre d'un conteneur Docker qu'il est charge de piloter.
Il reste donc un service de l'hote, y compris lorsque NodeConductor Controller
est lui-meme execute dans un conteneur.

### 2.1 Connexion locale

Lorsque NodeConductor et l'agent sont sur le meme hote, le conteneur
NodeConductor utilise un socket dedie :

```text
/run/nodeconductor-agent/nodeconductor-agent.sock
```

Seul ce socket est monte dans le conteneur NodeConductor. Le socket Docker
`/var/run/docker.sock` reste accessible uniquement a l'agent.

### 2.2 Connexion distante

Lorsque NodeConductor est sur une autre machine ou dans un autre conteneur
Proxmox, il contacte l'agent en HTTPS avec authentification mutuelle mTLS.

Une connexion identifie donc un agent et son transport, sans modifier le
comportement du driver Docker.

---

## 3. Perimetre de l'Agent Docker

L'agent expose une API metier restreinte. Il ne sert pas de relais transparent
vers l'API Docker.

Capacites initiales cibles :

- inventorier les projets Docker Compose et les conteneurs autonomes ;
- lister les conteneurs membres d'un projet Compose pour le diagnostic ;
- retourner l'etat Docker et le health check des membres ;
- demarrer ou arreter un projet Compose autorise ;
- demarrer ou arreter un conteneur autonome autorise ;
- annoncer la version et les capacites de l'agent ;
- appliquer et retourner la politique de gestion d'une cible pilotable.

Operations exclues de la premiere version :

- executer une commande libre dans un conteneur ;
- creer ou supprimer un conteneur ;
- modifier ses volumes, son reseau ou ses privileges ;
- piloter individuellement un conteneur membre d'un projet Compose ;
- accepter du Controller un chemin Compose, un repertoire de travail ou des
  arguments de ligne de commande arbitraires ;
- utiliser `compose up` ou `compose down` dans les operations exposees par
  NodeConductor ;
- transmettre une requete Docker arbitraire ;
- exposer des secrets Docker ou de l'hote.

Chaque operation possede un identifiant unique afin que l'agent puisse reconnaitre
une demande deja traitee et eviter une double execution.

---

## 4. Inventaire et politique de gestion

L'agent liste tous les conteneurs presents sur son moteur Docker, puis les
classe a partir des labels Compose officiels :

- les conteneurs appartenant au meme projet sont regroupes sous une cible
  `compose_project` ;
- un conteneur sans rattachement Compose devient une cible
  `standalone_container` ;
- un conteneur dont les metadonnees Compose sont incompletes ou incoherentes
  reste visible mais non pilotable jusqu'a clarification.

Dans NodeConductor, un projet Compose est affiche en priorite comme une seule
ressource. Ses conteneurs membres peuvent apparaitre dans son detail, avec leur
etat et leur health status, mais ne sont ni des cibles de service ni des cibles
de job distinctes. Les conteneurs autonomes restent affiches au meme niveau que
les projets Compose.

Trois etats de gestion sont retenus :

| Etat | Visibilite | Actions start/stop |
|---|---|---|
| `discovered` | visible | interdites |
| `managed` | visible | autorisees |
| `protected` | visible | interdites |

La politique automatique unique est :

```text
default_management_policy=discovered
```

Un utilisateur disposant des droits necessaires peut changer l'etat depuis
NodeConductor. Il peut notamment attribuer `managed` ou `protected`, puis retirer
la protection si son niveau d'autorisation le permet.

La politique porte sur le projet Compose complet ou sur le conteneur autonome.
Elle ne porte pas separement sur les conteneurs membres. La cible qui heberge
NodeConductor est identifiee par une configuration explicite de l'Agent et forcee
en `protected` : si NodeConductor appartient a un projet Compose, tout le projet
est protege ; s'il est autonome, son conteneur est protege. Cette protection ne
peut pas etre retiree depuis le Controller.

L'agent applique et persiste la politique effective. NodeConductor en conserve
une representation synchronisee pour l'interface et l'audit. Une divergence ne
doit jamais permettre une action que l'agent considere interdite.

Chaque transition de politique produit un event contenant au minimum :

- la cible concernee ;
- l'ancien et le nouvel etat ;
- l'identite de l'utilisateur autorise ;
- la date de la modification.

---

## 5. Modele d'une cible reelle

Les notions suivantes restent separees :

- **service** : ressource logique presentee a l'utilisateur ;
- **description** : role humain du service ;
- **driver** : implementation utilisee, par exemple `docker` ;
- **connection_id** : agent et transport permettant de joindre l'infrastructure ;
- **target_kind** : `compose_project` ou `standalone_container` pour Docker ;
- **target** : identifiant strict de la ressource chez ce driver ;
- **readiness check** : condition qui confirme la disponibilite reelle.

Exemple conceptuel :

```text
name: Snipe-IT
description: Gestion du parc informatique
driver: docker
connection_id: docker-host-principal
target_kind: compose_project
target: snipe-it
readiness_check: http
```

Pour un projet Compose, `target` contient l'identite stable du projet sur la
connexion concernee. Pour un conteneur autonome, il contient l'ID Docker complet.
Il ne contient jamais une commande libre, un chemin Compose fourni par le
Controller ou des arguments de ligne de commande.

L'identite operationnelle cible devient le quadruplet :

```text
(driver, connection_id, target_kind, target)
```

Les verrous et la detection des doublons utilisent cette identite et pas
seulement `service_id`.

---

## 6. Definition du succes

Le succes d'une commande ne suffit pas. Le worker doit observer l'etat attendu
du service.

Pour un demarrage :

```text
commande acceptee
  -> projet Compose ou conteneur autonome dans l'etat attendu
  -> readiness check reussi
  -> job succeeded
  -> service on
```

Pour un arret :

```text
commande acceptee
  -> projet Compose ou conteneur autonome arrete
  -> job succeeded
  -> service off
```

Pour un projet Compose, le succes n'est pas deduit du seul etat `running` d'un
conteneur. L'Agent agrege l'etat des membres attendus et le Controller applique
le readiness check du service. Les etats normalises cibles d'un projet sont
`stopped`, `starting`, `running`, `degraded`, `partial` et `unknown`.

Le readiness check est configurable par service :

- `docker_state` : etat du conteneur seulement ;
- `docker_health` : resultat du `HEALTHCHECK` Docker ;
- `http` : reponse HTTP attendue ;
- `tcp` : port TCP joignable.

Le driver retourne un resultat normalise et ne decide pas seul du statut metier
final du service.

---

## 7. Execution, verification et incertitude

Un job reel traverse deux phases internes lorsqu'une verification est necessaire :

```text
executing -> verifying -> resultat terminal
```

Pendant ces phases, le service reste `starting` ou `stopping`. Il n'est pas
necessaire d'ajouter un etat de service `verifying`.

Resultats possibles :

- `succeeded` : l'etat attendu est confirme ;
- `failed` : un echec ou un etat oppose est confirme ;
- `indeterminate` : le resultat reel ne peut pas etre etabli de maniere fiable ;
- `cancelled` : le job a ete annule selon les regles supportees.

L'etat de service `unknown` represente une cible dont l'etat reel n'est pas
determinable. `error` reste reserve a un echec confirme.

Apres une commande lente ou un timeout, le worker poursuit des verifications
bornees :

- etat attendu finalement observe : succes, avec les informations de lenteur ;
- etat oppose confirme : echec ;
- absence persistante d'information fiable : resultat `indeterminate` et service
  `unknown`.

---

## 8. File persistante et parallelisme

La file PostgreSQL est conservee. Elle assure la persistance, la tracabilite,
la reprise apres interruption et la regulation de charge.

Elle devient concurrente selon trois limites :

- une limite globale de jobs en execution ;
- une limite par connexion ou Agent Docker ;
- exactement un job actif par cible reelle.

Valeurs initiales confirmees pour le worker automatique :

```text
global concurrency: 4
per connection: 2
per target: 1
```

La prise d'un job doit etre atomique dans PostgreSQL. Deux workers ne doivent
jamais pouvoir reclamer le meme job.

### 8.1 Demandes concurrentes

Pour une cible possedant deja un job actif :

- meme action : retourner le job existant sans en creer un nouveau ;
- action opposee : rejeter avec `409 Conflict` ;
- aucune action active : creer un nouveau job `pending`.

Avant l'execution, le worker relit l'etat reel :

- l'etat souhaite est deja atteint : terminer en succes avec `no_op=true` ;
- l'action reste necessaire : l'executer ;
- l'etat est inconnu : appliquer la strategie de verification.

### 8.2 Attente excessive

Un job `pending` n'expire pas automatiquement par defaut. Le systeme mesure son
temps d'attente et peut produire `job.queue_delayed` au-dela d'un seuil.

Un futur champ optionnel `expires_at` pourra representer une demande qui n'a
plus de sens apres une date precise. Il ne remplace pas les limites de
parallelisme.

---

## 9. Timeouts, durees et anomalies

Le systeme distingue :

- `queue_duration` : creation du job jusqu'a sa prise par un worker ;
- `execution_duration` : prise du job jusqu'a la fin de l'action ;
- `verification_duration` : temps consacre a confirmer l'etat final ;
- `total_duration` : creation jusqu'au resultat terminal.

Le timeout d'execution commence lorsque le worker prend le job. Une attente en
file ne doit pas consommer le timeout de l'action.

Deux seuils restent distincts :

- un seuil statistique de lenteur, qui produit `job.duration_anomaly` avec la
  severite `warning` ;
- un hard timeout configure par driver, service ou action, qui borne le travail.

Les durees reelles sont analysees par cible, driver et action. La mediane et une
mesure de dispersion robuste sont preferees a une moyenne seule, afin que
quelques valeurs extremes ne faussent pas le comportement attendu.

Un job peut donc etre `succeeded` tout en ayant produit une anomalie de duree.

Les verifications sont repetees a un intervalle borne jusqu'au hard timeout. La
duree habituelle peut guider l'intervalle et le seuil de warning, mais elle ne
doit pas reduire automatiquement la limite de securite.

---

## 10. Simulation realiste

La simulation reproduit le meme cycle de vie metier sans effectuer aucun appel
infrastructure ou reseau reel.

Sa duree est determinee dans cet ordre :

1. historique reel de la meme cible et de la meme action ;
2. historique ou profil du meme driver et de la meme action ;
3. valeur par defaut configurable.

Une variation aleatoire faible et bornee rend la demonstration credible. Les
donnees simulees ne sont jamais reutilisees pour calculer les statistiques
reelles.

Deux vitesses sont prevues :

- mode realiste : attente effective pendant la duree simulee ;
- mode rapide : aucune attente significative, mais conservation de la duree
  simulee dans le resultat pour les tests fonctionnels.

Les erreurs simulees sont declenchees uniquement sur demande par defaut. Une
probabilite d'erreur configurable peut etre activee pour une demonstration.

Lorsqu'un service simule entre en erreur, cette erreur peut rester stable
jusqu'au prochain changement de jour ou au redemarrage de NodeConductor. Le but
est d'eviter qu'un service simule alterne artificiellement entre succes et echec
a chaque cycle.

---

## 11. Redemarrage et reconciliation

Au demarrage, NodeConductor ne fait pas confiance aveuglement aux statuts
persistes. Il lance une reconciliation :

1. interroger les agents disponibles ;
2. synchroniser l'inventaire des conteneurs ;
3. relire l'etat reel des cibles connues ;
4. corriger l'etat courant en base si necessaire ;
5. examiner les jobs restes `running` ;
6. determiner, par observation, s'ils ont reussi, echoue ou restent
   `indeterminate` ;
7. produire les events d'audit correspondants.

La reconciliation des services, la recuperation des jobs abandonnes et la
protection contre plusieurs workers sont trois responsabilites distinctes.

---

## 12. Demarrage et arret du moteur Docker

L'Agent Docker etant un service de l'hote, il pourra a terme detecter un moteur
Docker arrete et demander au gestionnaire de services de l'hote de le demarrer.
Cette capacite devra etre limitee a un service Docker connu ; aucun nom de
service ou commande systeme arbitraire ne sera accepte.

Le demarrage et l'arret du moteur Docker ne font pas partie du premier Agent
MVP. Ils ne peuvent pas etre testes correctement dans la situation actuelle,
ou NodeConductor depend du meme moteur Docker. Dans cette premiere etape :

- l'agent suppose Docker demarre ;
- un moteur inaccessible produit un resultat `engine_unavailable` ;
- la capacite future reste documentee, mais aucun contrat premature n'est fige ;
- les tests seront faits plus tard depuis une autre machine ou une VM dediee.

L'arret du moteur qui heberge NodeConductor interromprait le Controller et doit
donc rester interdit dans cette topologie.

---

## 13. Securite

Regles non negociables :

- authentifier le Controller aupres de l'agent ;
- chiffrer les connexions distantes avec mTLS ;
- limiter chaque operation aux capacites explicites de l'agent ;
- verifier la politique `managed` avant toute action ;
- ne jamais accepter une commande Docker ou systeme arbitraire ;
- ne jamais exposer de secret dans une reponse, un log ou un event ;
- borner les tailles, les durees et le nombre de travaux concurrents ;
- auditer les changements de politique et les actions reelles ;
- rendre les operations idempotentes autant que possible.

Une erreur du Controller ne doit jamais contourner une interdiction appliquee
par l'agent.

---

## 14. Ordre de developpement retenu

Le developpement sera decoupe en lots independants :

1. contrats et modele de donnees ;
2. worker concurrent, prise atomique et verrous par cible ;
3. Agent Docker MVP, inventaire et politique de gestion ;
4. driver Docker, start, stop, inspect et readiness checks ;
5. durees, anomalies et simulation realiste ;
6. reconciliation au redemarrage et recuperation des jobs abandonnes.

Chaque lot doit mettre a jour la documentation de l'etat implemente. Les valeurs
precises de parallelisme, de polling et de timeout restent configurables et
seront fixees avec les tests de chaque lot.

---

## 15. Etat implemente : lot 1, contrats et modele de donnees

Le premier lot est maintenant implemente. PostgreSQL contient :

- `agent_connections`, avec un identifiant stable, une description, le
  transport `unix_socket` ou `https`, un endpoint non secret et
  `default_management_policy=discovered` ;
- `targets`, avec `driver`, `connection_id`, `target` et la politique effective
  `discovered`, `managed` ou `protected` ;
- une contrainte d'unicite sur `(driver, connection_id, target)` ;
- `service_targets`, qui associe au plus une cible a un service et, en v1, au
  plus un service a une cible ; l'association porte le type de readiness check
  `docker_state`, `docker_health`, `http` ou `tcp` ;
- les colonnes nullables `queue_duration_ms`, `execution_duration_ms`,
  `verification_duration_ms` et `total_duration_ms` sur les jobs.

Les contrats Python representent ces memes valeurs. Le resultat de job
`indeterminate` et l'etat de service `unknown` sont acceptes. Dans la simulation
MVP, un resultat `indeterminate` termine le job avec ce resultat, place le
service en `unknown` et produit `job.indeterminate` avec la severite `warning`.

Ce lot n'implemente pas :

- d'endpoint de gestion des connexions, cibles ou politiques ;
- de stockage ou d'exposition de credentials d'agent ;
- l'Agent Docker, le driver Docker ou un appel reseau/infrastructure ;
- l'execution des readiness checks ni leur configuration detaillee HTTP/TCP ;
- le calcul des durees, qui restent `null` jusqu'au lot metriques ;
- la phase `verifying`, la prise concurrente, les verrous ou la reconciliation.

---

## 16. Etat implemente : lot 2, concurrence et verrous

Le worker automatique utilise maintenant la file PostgreSQL de facon
concurrente. Les invariants persistants sont :

- `service_targets.target_id` est unique : une cible canonique appartient a un
  seul service en v1 ;
- `jobs.target_id` est nullable et reference `targets` avec suppression
  restrictive ; il fige la cible connue lors de la creation du job ;
- les jobs historiques ou simules sans cible restent valides avec
  `target_id=null` ;
- deux index partiels interdisent plusieurs jobs `pending` ou `running` pour un
  meme service ou une meme cible ;
- un trigger PostgreSQL interdit de modifier `driver`, `connection_id` ou
  `target` apres creation d'une cible.

La demande `start` ou `stop` verrouille la ligne service dans une transaction,
lit son association, cherche un job actif par service et par cible, puis cree le
job si l'etat le permet. Deux demandes simultanees obtiennent donc soit le meme
job pour la meme action, soit un conflit pour des actions opposees.

Le claim automatique :

- reserve une courte section critique avec un advisory lock transactionnel
  PostgreSQL partage par toutes les instances ;
- verifie la capacite globale et la capacite de la connexion ;
- selectionne une ligne avec `FOR UPDATE SKIP LOCKED` ;
- passe cette ligne de `pending` a `running` dans la meme instruction SQL.

`WorkerLoopController` remplit immediatement les places libres, execute les jobs
de cibles differentes en parallele, puis remplit une place des qu'une execution
se termine. Les limites par defaut sont :

```text
NODECONDUCTOR_WORKER_MAX_CONCURRENCY=4
NODECONDUCTOR_WORKER_MAX_CONCURRENCY_PER_CONNECTION=2
per target=1
```

Pendant son arret, la boucle ne commence plus de nouveau claim. Elle attend les
jobs deja lances. Les facades manuelles `run_job` et `simulate-complete` sont
conservees pour les tests et la demonstration ; elles claim un id precis et ne
peuvent plus executer un job deja pris par un autre worker. Elles ne constituent
pas l'ordonnanceur automatique et n'appliquent pas ses quotas globaux/par
connexion.

Ce lot n'ajoute toujours aucun Agent Docker, appel Docker ou reseau, readiness
check reel, retry, reconciliation, annulation d'un job `running`, calcul de
duree ou event `job.queue_delayed`.

---

## 17. Etat implemente : lot 3A, Agent Docker MVP read-only

Le composant autonome `agent/` est maintenant implemente avec son propre package
Python `nodeconductor_agent`. Il utilise FastAPI/Uvicorn, le SDK Docker officiel
derriere une interface injectable et SQLite localement. Il n'importe ni le
backend Controller ni PostgreSQL.

L'API interne permet :

- de lire la sante de l'agent et la disponibilite du moteur ;
- de lire les versions Agent/Docker et les capacites effectivement disponibles ;
- de lister les conteneurs avec `limit` et `offset` bornes ;
- d'inspecter un conteneur par son ID Docker complet ;
- de lire et modifier sa politique `discovered`, `managed` ou `protected` ;
- d'auditer localement chaque demande de politique.

L'inventaire ne renvoie que l'ID, le nom, l'etat, le health status et la date de
creation. Les contrats de reponse excluent la configuration brute, les variables
d'environnement, mounts, secrets et labels. Les erreurs Docker sont normalisees
sans texte technique provenant de l'hote.

SQLite indexe les politiques par ID Docker immuable. Le nom courant n'est jamais
une cle d'autorisation : un ID connu conserve sa politique apres renommage, mais
un nouvel ID reutilisant ce nom repart en `discovered`. Les operations de
politique utilisent un UUID `operation_id`. Un rejeu identique retourne le
resultat initial ; une reutilisation contradictoire produit `409 Conflict`.

Le transport par defaut est le socket Unix dedie. Aucun TCP en clair n'est
supporte. Le mode HTTPS configure Uvicorn avec certificat client obligatoire et
refuse de demarrer si le certificat serveur, la cle ou la CA client est absent
ou invalide. L'emission de certificats n'est pas implementee.

Ce lot 3A n'ajoute pas :

- start, stop ou restart de conteneur et aucun pilotage de `docker.service` ;
- integration entre le worker et l'agent ;
- readiness check reel, retry ou reconciliation ;
- synchronisation des politiques avec les tables PostgreSQL du Controller ;
- API publique Controller pour les politiques ;
- authentification ou autorisation utilisateur ; le champ `actor` est seulement
  une donnee d'audit bornee.

L'installation `systemd` decrite dans `agent/README.md` reste un guide futur. Elle
n'a pas ete validee depuis l'environnement Windows de developpement.

---

## 18. Etat implemente : lot 3B, client Controller et inventaire synchronise

Le Controller possede maintenant un `AgentClient` injectable. L'implementation
HTTP supporte :

- le socket Unix dedie avec `httpx.HTTPTransport(uds=...)` ;
- HTTPS uniquement avec validation du serveur, certificat client et cle charges
  dans un contexte mTLS ;
- des delais separes de connexion et de reponse ;
- une taille maximale de reponse, une page de 100 conteneurs maximum et un
  nombre total de pages configurable et borne ;
- des erreurs normalisees qui ne recopient jamais le corps distant.

Les chemins de certificat ne sont pas stockes dans PostgreSQL. La table
`agent_connections` conserve uniquement `agent_id` attendu et une
`credential_ref` nullable. Un resolver externe transforme cette reference en
certificat client, cle et CA serveur depuis la configuration du processus.

Avant l'inventaire, le Controller verifie `agent_id`, la coherence de la version
Agent, `api_version=v1`, la disponibilite du moteur et la capacite
`container_list`. Il charge ensuite toutes les pages et valide total, offsets,
taille et absence de doublon avant toute ecriture.

Une synchronisation complete applique dans une transaction PostgreSQL :

- `target` egal a l'ID Docker complet ;
- le nom courant dans `display_name` ;
- la politique effective annoncee par l'Agent ;
- l'etat, le health status, `last_seen_at` et `is_present=true` ;
- `is_present=false` pour une cible absente du snapshot complet, sans suppression.

Une page invalide ou indisponible annule le snapshot avant PostgreSQL. Le dernier
inventaire reste donc intact et aucune cible n'est marquee absente. Les events
implementes sont `target.discovered`, `agent.inventory_synchronized`,
`agent.inventory_unavailable` et `agent.inventory_rejected`.

Ce lot reste une facade interne appelee explicitement. Il n'ajoute ni endpoint
public de synchronisation/politique, ni planification automatique, ni commande
Docker, ni branchement du worker, readiness check ou reconciliation des jobs.

---

## 19. Etat implemente : lot 3C, deadlines cooperatives

Le worker n'utilise plus de `ThreadPoolExecutor` imbrique pour simuler un hard
timeout. L'executor est appele directement dans le thread de travail deja cree
par `WorkerLoopController`. Aucun thread Python n'est tue ou abandonne.

Chaque claim persiste un UUID `jobs.operation_id`, nullable avant le premier
claim et unique lorsqu'il existe. Un `COALESCE` conserve cette identite si un
futur mecanisme de reconciliation rejoue le meme job. Deux jobs distincts ne
peuvent pas partager le meme `operation_id`.

L'executor recoit un `WorkerExecutionContext` contenant cet identifiant et une
deadline fondee sur `time.monotonic`. Il doit :

- verifier le budget avant chaque dispatch ;
- borner chaque attente, polling ou appel I/O avec `remaining_seconds()` ;
- utiliser le minimum entre le timeout propre de l'I/O et le temps restant ;
- signaler `failed` pour une expiration avant dispatch ou un echec confirme ;
- signaler `indeterminate` lorsque la requete a pu partir sans resultat fiable.

Le client HTTP de l'Agent accepte maintenant un budget optionnel par requete et
le combine avec ses limites de connexion/reponse. La synchronisation read-only
existante ne fournit pas ce parametre et conserve donc son comportement 3B.

La deadline est cooperative. Si un executor interne ne respecte pas le contrat,
le job reste `running`, continue de compter dans les quotas et conserve le verrou
de sa cible jusqu'au retour reel de l'executor. L'arret du Controller attend lui
aussi ce retour. Le passage interne `executing -> verifying` reste une cible :
aucun etat persistant `verifying`, commande Agent mutatrice, readiness check,
retry, annulation `running` ou reconciliation n'est ajoute dans ce lot.

---

## 20. Decision post-3C : projets Compose et conteneurs autonomes

Le pilotage Docker futur porte en priorite sur les projets Compose. Un conteneur
membre reste observable dans le detail de son projet, mais ne peut pas etre
demarre ou arrete individuellement par NodeConductor. Un conteneur sans projet
Compose reste une cible pilotable autonome.

La presentation cible est donc :

```text
connexion Docker
  -> projet Compose
       -> conteneurs membres observes
  -> conteneur autonome
```

Seules les cibles `managed` sont pilotables. Les cibles `discovered` restent en
lecture seule et les cibles `protected` interdisent toute action. La cible qui
heberge NodeConductor est forcee en `protected` par l'Agent, qu'il s'agisse d'un
projet Compose ou d'un conteneur autonome.

### Compatibilite avec les lots implementes

Les fondations suivantes restent adaptees sans changement de principe :

- connexion stable au meme Agent Docker ;
- association d'un service logique a une cible canonique ;
- snapshot `jobs.target_id`, unicite d'un job actif et verrou par cible ;
- limites globale, par connexion et par cible ;
- `operation_id`, idempotence attendue et deadline cooperative ;
- politiques `discovered`, `managed` et `protected`.

Le lot 4A implemente maintenant ce modele d'inventaire read-only. L'Agent
retourne des ressources typees, regroupe les membres Compose, isole les
ressources ambigues et force la protection configuree. PostgreSQL, SQLite et la
synchronisation Controller utilisent `target_kind`. Aucun appel Docker
`start` ou `stop` n'est encore implemente.

### Limites permanentes du pilotage Compose

Le pilotage Compose utilise uniquement les equivalents de `start` et `stop` sur
un projet existant et decouvert par l'Agent. `up` et `down` sont durablement hors
du contrat NodeConductor : aucune API, action de job ou capacite Agent ne doit
permettre de creer, recreer ou supprimer les ressources d'un projet Compose.
Cette interdiction protege notamment les donnees persistantes des services de
production tels que Snipe-IT.

Le Controller ne transmet jamais de chemin de fichier Compose. L'Agent ne doit
pas accepter de fichier, repertoire de travail, argument de ligne de commande ou
option Compose arbitraire. L'eventuelle administration manuelle d'un projet avec
`up` ou `down` reste une operation externe a NodeConductor.

---

## 21. Etat implemente : lot 4A, inventaire Docker Compose type

Le lot 4A est implemente sur :

```text
feature/docker-compose-inventory
```

L'Agent annonce le contrat `api_version=v2` et la capacite
`resource_inventory_v1`. `GET /api/v2/resources` fournit un inventaire
type et pagine. La premiere page cree un `snapshot_id` opaque ; toutes les
pages suivantes reutilisent exactement ce snapshot. Le Controller refuse la
synchronisation si l'identite, la version, la capacite, le total, l'offset,
l'identifiant ou la date du snapshot changent.

Seuls les labels `com.docker.compose.project` et
`com.docker.compose.service` sont lus. Ils sont immediatement reduits a une
identite et ne sont jamais exposes. Deux labels presents, non vides, bornes et
sans chemin forment un membre coherent. Aucun label pertinent forme un
conteneur autonome. Toute autre combinaison produit une ressource
`ambiguous`, visible pour le diagnostic mais sans `target_kind`, politique
ou possibilite de pilotage.

### Regles d'agregation Compose

L'agregat est calcule dans cet ordre :

1. `unknown` si un membre est `unknown`, `removing` ou `dead`, ou si
   son health status est `unknown` ;
2. `stopped` si tous les membres sont `created` ou `exited` ;
3. `partial` si des membres actifs et arretes coexistent ;
4. `degraded` si un membre restant est `paused` ou `unhealthy` ;
5. `starting` si un membre est `restarting` ou a un health status
   `starting` ;
6. `running` si tous les membres sont `running` ;
7. `unknown` pour tout autre cas.

Cet agregat de l'inventaire n'est pas un readiness check et ne peut pas, a lui
seul, faire reussir un job.

### Migration et compatibilite

La migration est strictement additive :

- les anciennes lignes `targets` recoivent
  `target_kind=standalone_container` par defaut ;
- l'unicite devient
  `(driver, connection_id, target_kind, target)` et ces quatre champs sont
  immuables ;
- aucune cible, association `service_targets` ou ligne `jobs` n'est
  supprimee ou reassociee ;
- une ancienne cible dont l'ID est maintenant un membre Compose conserve son
  ID PostgreSQL et sa politique historique, mais devient
  `is_pilotable=false` et `is_present=false` ;
- la creation d'une association, d'un job ou le claim d'un job sur une telle
  cible est refuse ; les jobs historiques restent interpretables ;
- les membres vivent dans `compose_members`, sans politique, association de
  service ou cible de job ;
- les ambiguites vivent dans `docker_inventory_issues` ;
- SQLite migre les anciennes politiques de conteneur vers la cle
  `(standalone_container, ID Docker complet)`.

Une protection configuree est persistee avec `protection_forced=true`.
L'Agent refuse sa diminution et PostgreSQL empeche egalement le Controller de
remplacer `protected`. Une identite configuree absente ou devenue membre d'un
autre projet produit respectivement `configured_absent` ou
`configured_inconsistent`; aucune recherche approximative par nom n'existe.

La synchronisation applique dans une seule transaction les projets, conteneurs
autonomes, membres et diagnostics. Une page manquante ou invalide n'ecrit rien
et ne marque aucune ressource absente. Les events ne contiennent que les
identites typees et les compteurs ; aucun label brut, secret ou chemin local.

L'endpoint v1 `/containers` reste une transition de lecture et de politique
pour les seuls conteneurs autonomes. La version v2 des capabilities force un
ancien Controller a refuser le contrat au lieu de synchroniser des membres
Compose comme des cibles individuelles.

Ce lot n'ajoute aucune commande Docker mutatrice, commande Compose, readiness
reel, branchement du worker, retry ou reconciliation.

---

## 22. Etat implemente : lot 4B, actions Agent Docker restreintes

Le lot 4B est implemente sans commit sur :

```text
feature/docker-agent-actions
```

Il reste limite au package Agent. Le worker Controller, les endpoints publics,
les readiness checks, les retries et la reconciliation ne l'appellent pas.

L'endpoint interne
`POST /api/v2/resources/{target_kind}/{target}/actions` accepte un UUID
`operation_id`, un `actor` borne et `action=start|stop`. Les modeles refusent
les champs inconnus. L'Agent relit toujours son inventaire et sa politique
locale avant dispatch : cible presente, operationnelle, pilotable, `managed`
et non protegee. Un membre Compose, une ambiguite, une cible `discovered` ou
`protected` et la ressource hebergeant NodeConductor sont refuses localement.

Pour un conteneur autonome, l'adaptateur SDK officiel n'expose que
`start_container(id)` et `stop_container(id, timeout)`. Un etat deja conforme
retourne `completed` sans appel au moteur. Le delai d'arret est configure
localement et borne ; aucun appel de suppression ou de forcage n'existe.

Pour Compose, le Controller ne fournit toujours aucune donnee d'execution. Le
registre local `/etc/nodeconductor-agent/compose-projects.toml` associe une
identite decouverte exacte a un nom de projet, un repertoire resolu, une liste
bornee de fichiers reguliers resolus et un delai d'arret de 1 a 300 secondes.
Une entree absente refuse l'action ; un registre invalide echoue avant dispatch.
Le runner injectable construit une liste d'arguments fixe, utilise
`shell=False`, ne selectionne aucun service et n'execute que les sous-ordres
Compose `start` ou `stop` sur le projet complet.

Les capabilities sont explicites : `standalone_start_stop` avec le moteur
disponible ; `compose_start_stop` seulement si le registre contient un projet
valide et si l'executable Compose repond au probe local. Aucune capability ne
suggere une creation, une reconstruction ou une suppression de ressources.

### Resultats, idempotence et crash

La reponse distingue :

| Statut | Signification Agent |
|---|---|
| `completed` | l'appel d'infrastructure est termine et l'etat Docker demande a ete observe |
| `rejected` | une regle d'identite, de politique, de protection ou de concurrence refuse la demande |
| `failed` | l'echec est confirme ou a eu lieu avant dispatch |
| `indeterminate` | un dispatch a pu avoir lieu mais son issue n'est pas connue |

`completed` n'est pas une readiness metier. La reponse ne contient qu'une vue
filtree de l'identite, de l'etat, du health status, de la politique et du
caractere pilotable ; aucun chemin, argument, sortie brute, label ou secret.

SQLite enregistre chaque operation avant dispatch. Le meme `operation_id` et
la meme requete rejouent le resultat persiste sans nouvel appel. Une
reutilisation avec acteur, cible ou action differente retourne `409`. Un index
partiel garantit une seule operation `in_progress` par ressource. Une autre
operation concurrente sur cette ressource est refusee sans file locale ; des
ressources distinctes conservent des verrous independants et peuvent avancer en
parallele.

Le verrou local reste tenu jusqu'au retour synchrone de l'adaptateur et a la
verification d'etat : aucun thread d'infrastructure n'est abandonne en
arriere-plan. Au demarrage, une ligne SQLite encore `in_progress` est convertie
en `indeterminate` et n'est jamais redispatchee automatiquement. Les erreurs
persistantes sont des codes et messages fixes ; aucune sortie d'adaptateur
n'entre en base.

La validation Linux/systemd, le probe Compose reel et tout test mutateur reel
restent non executes dans l'environnement Windows de developpement. Un futur
test reel devra designer explicitement une stack de test autorisee avec un
opt-in distinct ; il ne selectionnera jamais une autre stack et n'utilisera pas
Snipe-IT.
