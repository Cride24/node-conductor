# NodeConductor Agent

`nodeconductor-agent` est un composant Python deployable independamment du
Controller. Le lot MVP actuel expose uniquement l'inventaire Docker en lecture
seule et des politiques locales. Il n'a aucune dependance a PostgreSQL ni au
package `nodeconductor` du backend.

## API interne implementee

```text
GET /api/v1/health
GET /api/v1/capabilities
GET /api/v1/containers?limit=50&offset=0
GET /api/v1/containers/{full_container_id}
PUT /api/v1/containers/{full_container_id}/management-policy
```

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

Les reponses d'inventaire contiennent uniquement l'ID Docker complet, le nom
courant, l'etat, le health status, la date de creation et la politique. Elles
n'exposent pas les variables d'environnement, mounts, configurations brutes,
secrets ni labels Docker.

## Persistance locale

SQLite conserve :

- la politique `discovered`, `managed` ou `protected`, indexee par ID Docker ;
- le nom courant uniquement comme information d'affichage ;
- chaque operation de politique avec son `operation_id`, son acteur, l'ancienne
  et la nouvelle politique et sa date.

La politique par defaut est toujours `discovered`. Un ID Docker deja connu
conserve sa politique meme si son nom change. Un nouveau conteneur qui reutilise
un ancien nom recoit une nouvelle entree `discovered`.

Le registre d'audit fournit aussi l'idempotence. Le meme `operation_id` et le
meme contenu retournent exactement le resultat initial sans second audit. Une
reutilisation contradictoire de l'identifiant retourne `409 Conflict`.

## Configuration

Valeurs locales par defaut :

```text
NODECONDUCTOR_AGENT_TRANSPORT=unix_socket
NODECONDUCTOR_AGENT_UNIX_SOCKET=/run/nodeconductor-agent/nodeconductor-agent.sock
NODECONDUCTOR_AGENT_DATABASE_PATH=/var/lib/nodeconductor-agent/agent.sqlite3
NODECONDUCTOR_AGENT_DOCKER_TIMEOUT_SECONDS=5
NODECONDUCTOR_AGENT_MAX_REQUEST_BODY_BYTES=16384
```

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

Le test d'integration utilise uniquement `list` et `inspect` sur les conteneurs
deja presents. Il ne cree, ne demarre, n'arrete et ne supprime rien. Il est
ignore si le SDK ou le moteur Docker est indisponible, ou explicitement avec :

```text
NODECONDUCTOR_AGENT_SKIP_DOCKER_INTEGRATION=1
```

## Hors perimetre actuel

- start, stop ou restart d'un conteneur ;
- pilotage de `docker.service` ;
- readiness checks ;
- integration du worker ou synchronisation avec PostgreSQL ;
- API Controller publique de politique ;
- autorisation utilisateur NodeConductor ;
- emission automatique de certificats.
