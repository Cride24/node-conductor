# NodeConductor Agent

`nodeconductor-agent` est un composant Python deployable independamment du
Controller. Il expose l'inventaire Docker type, des politiques locales et les
seules mutations autorisees `start`/`stop` sur des conteneurs autonomes ou des
projets Compose preenregistres. Il n'a aucune dependance a PostgreSQL ni au
package `nodeconductor` du backend.

## API interne implementee

```text
GET /api/v1/health
GET /api/v1/capabilities
GET /api/v2/resources?limit=50&offset=0
GET /api/v2/resources?limit=50&offset=50&snapshot_id={uuid}
PUT /api/v2/resources/{target_kind}/{target}/management-policy
POST /api/v2/resources/{target_kind}/{target}/actions
GET /api/v1/containers?limit=50&offset=0
GET /api/v1/containers/{full_container_id}
PUT /api/v1/containers/{full_container_id}/management-policy
```

`target_kind` vaut `compose_project` ou `standalone_container`. L'endpoint
`/containers` est conserve comme transition v1, mais ne retourne que les
conteneurs sans aucun rattachement Compose pertinent. Un membre Compose ou une
ressource ambigue ne peut donc jamais recevoir une politique individuelle.

La premiere page `/resources` cree un snapshot opaque. Les pages suivantes
doivent reutiliser son `snapshot_id`; un identifiant absent ou expire retourne
`409` sans produire un inventaire partiel.

Le corps d'une action v2 contient uniquement :

```json
{
  "operation_id": "018f4db8-6d79-7fc1-a921-4ec37e97fb14",
  "actor": "controller:operator-42",
  "action": "start"
}
```

Les champs inconnus et toute action autre que `start` ou `stop` sont refuses.
Une reponse distingue `completed`, `rejected`, `failed` et `indeterminate`.
`completed` confirme seulement la fin de l'action d'infrastructure et
l'observation de l'etat Docker demande ; ce n'est pas une readiness metier.
L'etat retourne est filtre et ne contient ni membre Compose, chemin, commande,
sortie brute, label, variable d'environnement, mount ou secret.

Le corps du `PUT` contient :

```json
{
  "operation_id": "018f4db8-6d79-7fc1-a921-4ec37e97fb14",
  "actor": "controller:operator-42",
  "management_policy": "managed"
}
```

`actor` est une information d'audit bornee, pas une preuve d'autorisation. Il
n'existe pas encore d'authentification utilisateur NodeConductor. Le transport
local est protege par les permissions du socket Unix ; le transport distant
exige un certificat client mTLS.

Les reponses `health` et `capabilities` contiennent aussi `agent_id`. Cet
identifiant stable permet au Controller de refuser un Agent qui ne correspond
pas a la connexion attendue. Il ne doit pas changer a chaque redemarrage.
Avec un moteur disponible, `standalone_start_stop` annonce le SDK restreint.
`compose_start_stop` n'est annonce que si le registre contient au moins un
projet valide et si `docker compose` est effectivement utilisable. Aucune
capability ne couvre l'administration du cycle de vie Compose.

Les reponses d'inventaire contiennent les projets Compose, leurs membres et les
conteneurs autonomes. Pour chaque membre, seuls l'ID Docker complet, le nom, le
service Compose, l'etat, le health status, la presence et la derniere
observation sont exposes. Les labels bruts, variables d'environnement, mounts,
commandes, chemins Compose, configurations brutes et secrets ne sont jamais
retournes. Une ressource aux labels Compose incomplets ou invalides est visible
avec `classification=ambiguous`, `target_kind=null` et `operable=false`.

## Persistance locale

SQLite conserve :

- la politique `discovered`, `managed` ou `protected`, indexee par
  `(target_kind, target)` ;
- le nom courant uniquement comme information d'affichage ;
- chaque operation de politique avec son `operation_id`, son acteur, l'ancienne
  et la nouvelle politique et sa date ;
- chaque action avec sa requete, son statut filtre, ses dates et, si disponible,
  l'etat Docker filtre observe.

La politique par defaut est toujours `discovered`. Un ancien registre indexe
par ID Docker est migre vers `standalone_container` sans perte de politique.
Un ID Docker autonome deja connu conserve sa politique meme si son nom change.
Un membre Compose n'a jamais de politique propre.

Le registre d'audit fournit aussi l'idempotence. Le meme `operation_id` et le
meme contenu retournent exactement le resultat initial sans second audit. Une
reutilisation contradictoire de l'identifiant retourne `409 Conflict`.

Pour les actions, l'operation est inseree avant tout dispatch. Un index SQLite
n'autorise qu'une ligne `in_progress` par ressource. Deux requetes concurrentes
identiques portant le meme `operation_id` partagent le resultat d'un seul
dispatch. Une autre operation sur la meme ressource est refusee sans file
d'attente, tandis que des ressources distinctes peuvent avancer en parallele.
Au redemarrage de l'Agent, toute operation restee `in_progress` devient
`indeterminate` et n'est jamais redispatchee automatiquement. Aucune sortie
brute d'un adaptateur n'est conservee.

## Configuration

Valeurs locales par defaut :

```text
NODECONDUCTOR_AGENT_ID=docker-agent-local
NODECONDUCTOR_AGENT_TRANSPORT=unix_socket
NODECONDUCTOR_AGENT_UNIX_SOCKET=/run/nodeconductor-agent/nodeconductor-agent.sock
NODECONDUCTOR_AGENT_DATABASE_PATH=/var/lib/nodeconductor-agent/agent.sqlite3
NODECONDUCTOR_AGENT_DOCKER_TIMEOUT_SECONDS=5
NODECONDUCTOR_AGENT_MAX_REQUEST_BODY_BYTES=16384
NODECONDUCTOR_AGENT_COMPOSE_REGISTRY=/etc/nodeconductor-agent/compose-projects.toml
NODECONDUCTOR_AGENT_CONTAINER_STOP_TIMEOUT_SECONDS=30
NODECONDUCTOR_AGENT_PROTECTED_TARGET_KIND=compose_project
NODECONDUCTOR_AGENT_PROTECTED_TARGET=nodeconductor
```

Chaque installation doit remplacer `docker-agent-local` par un identifiant
stable et unique dans son environnement.

Les deux variables `PROTECTED_TARGET_*` sont optionnelles mais indissociables.
Pour un conteneur autonome, `PROTECTED_TARGET` doit etre son ID Docker complet.
Pour un projet Compose, il s'agit de l'identite de projet retournee par
l'inventaire. La ressource correspondante est forcee en `protected`; le
Controller ne peut pas retirer cette protection. Une identite absente ou
incoherente est signalee explicitement par `protection_status`.

## Registre Compose local de confiance

Un projet Compose reste visible sans etre autorise. Pour devenir pilotable, il
doit avoir une politique effective `managed` **et** une entree locale exacte :

```toml
[projects.snipe-it]
project_name = "snipe-it"
working_directory = "/srv/snipe-it"
compose_files = ["/srv/snipe-it/compose.yml"]
stop_timeout_seconds = 30
```

Le fichier est charge uniquement par l'Agent. Le chemin du registre, le
repertoire de travail et chaque fichier Compose doivent etre absolus ; les
chemins sont resolus, les repertoires/fichiers verifies et le delai borne entre
1 et 300 secondes. La cle TOML doit etre strictement identique a
`project_name`, lui-meme strictement identique au projet decouvert. Une
configuration invalide echoue avant dispatch et n'active pas la capability
`compose_start_stop`.

Permissions Linux recommandees, a adapter a l'installation : repertoire
`/etc/nodeconductor-agent` possede par `root:nodeconductor-agent` en `0750`,
registre possede par `root:nodeconductor-agent` en `0640`, fichiers Compose
lisibles par le compte Agent mais non modifiables par lui. Le Controller et le
compte desservant son API ne doivent pas pouvoir modifier ce registre. Ces
permissions n'ont pas ete validees depuis l'environnement Windows actuel.

Le runner construit exclusivement une liste d'arguments `docker compose` avec
le nom, le repertoire et les fichiers provenant de ce registre, puis le
sous-ordre `start` ou `stop`. Aucun service individuel ni argument de requete
n'est ajoute. L'execution utilise `shell=False`. L'arret utilise uniquement
`stop_timeout_seconds` ; aucun mecanisme de suppression forcee n'existe.

Le seul transport TCP supporte est HTTPS avec certificat client obligatoire :

```text
NODECONDUCTOR_AGENT_TRANSPORT=https
NODECONDUCTOR_AGENT_HTTPS_HOST=127.0.0.1
NODECONDUCTOR_AGENT_HTTPS_PORT=8443
NODECONDUCTOR_AGENT_TLS_CERTIFICATE=/etc/nodeconductor-agent/server.crt
NODECONDUCTOR_AGENT_TLS_PRIVATE_KEY=/etc/nodeconductor-agent/server.key
NODECONDUCTOR_AGENT_TLS_CLIENT_CA=/etc/nodeconductor-agent/client-ca.crt
```

Le demarrage HTTPS echoue avant l'ecoute si le certificat serveur, la cle ou la
CA client manque, n'est pas lisible ou n'est pas chargeable. Le lot n'emet et ne
renouvelle aucun certificat.

## Installation future comme service systeme

L'agent doit etre installe sur l'hote Docker, jamais dans un conteneur qu'il
pourrait etre amene a piloter. Exemple indicatif pour une future validation
Linux :

```text
python3 -m venv /opt/nodeconductor-agent/venv
/opt/nodeconductor-agent/venv/bin/pip install /opt/nodeconductor-agent/source
```

Unite `systemd` indicative pour le socket Unix :

```ini
[Unit]
Description=NodeConductor Docker Agent
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=nodeconductor-agent
Group=docker
UMask=0007
RuntimeDirectory=nodeconductor-agent
StateDirectory=nodeconductor-agent
Environment=NODECONDUCTOR_AGENT_TRANSPORT=unix_socket
ExecStart=/opt/nodeconductor-agent/venv/bin/nodeconductor-agent
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/run/nodeconductor-agent /var/lib/nodeconductor-agent
ReadOnlyPaths=/etc/nodeconductor-agent/compose-projects.toml

[Install]
WantedBy=multi-user.target
```

L'appartenance au groupe donnant acces au socket Docker est un privilege eleve.
Le compte doit etre dedie et l'API de l'agent doit rester strictement limitee.
Cet exemple n'a pas ete valide avec `systemd` depuis l'environnement Windows de
developpement ; les chemins, permissions, options de durcissement et le cycle de
redemarrage restent a valider sur une VM Linux avant production.

## Tests

Depuis `agent/` :

```text
poetry install
poetry run pytest
```

Le test d'integration reel active par defaut utilise uniquement `list` et
`inspect` sur les conteneurs deja presents. Il ne cree, ne demarre, n'arrete et
ne supprime rien. Il est
ignore si le SDK ou le moteur Docker est indisponible, ou explicitement avec :

```text
NODECONDUCTOR_AGENT_SKIP_DOCKER_INTEGRATION=1
```

Aucun test mutateur reel n'est active dans ce lot. Les tests `start`/`stop`
utilisent exclusivement des gateways et runners injectables. Une future preuve
reelle devra exiger a la fois un opt-in explicite et l'identite exacte d'une
stack de test autorisee ; elle ne devra jamais choisir automatiquement une
stack existante ni utiliser Snipe-IT.

## Hors perimetre actuel

- toute mutation autre que `start` et `stop` ;
- pilotage de `docker.service` ;
- readiness checks ;
- integration mutatrice du worker ;
- API Controller publique de politique ;
- autorisation utilisateur NodeConductor ;
- emission automatique de certificats.
