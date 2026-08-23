# Worker reel et Agent Docker

Ce document fixe les decisions de conception prises avant l'implementation du
premier worker reel de NodeConductor. Il complete `Worker-MVP.md`, qui decrit
l'etat actuellement implemente, et `Jobs-et-actions.md`, qui decrit les regles
metier des jobs.

Le contenu de ce document est une cible de developpement. Il ne signifie pas
que l'Agent Docker, le worker concurrent ou les nouveaux statuts sont deja
implementes.

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
/run/nodeconductor-agent.sock
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

Capacites initiales :

- lister et inspecter les conteneurs ;
- retourner l'etat Docker et le health check d'un conteneur ;
- demarrer un conteneur autorise ;
- arreter un conteneur autorise ;
- annoncer la version et les capacites de l'agent ;
- appliquer et retourner la politique de gestion d'un conteneur.

Operations exclues de la premiere version :

- executer une commande libre dans un conteneur ;
- creer ou supprimer un conteneur ;
- modifier ses volumes, son reseau ou ses privileges ;
- transmettre une requete Docker arbitraire ;
- exposer des secrets Docker ou de l'hote.

Chaque operation possede un identifiant unique afin que l'agent puisse reconnaitre
une demande deja traitee et eviter une double execution.

---

## 4. Inventaire et politique de gestion

L'agent liste tous les conteneurs presents sur son moteur Docker. Un nouveau
conteneur devient visible dans NodeConductor sans devenir automatiquement
pilotable.

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
- **target** : identifiant strict de la ressource chez ce driver ;
- **readiness check** : condition qui confirme la disponibilite reelle.

Exemple conceptuel :

```text
name: Jellyfin
description: Serveur multimedia
driver: docker
connection_id: docker-host-principal
target: jellyfin
readiness_check: docker_health
```

Le champ `target` contient un nom ou un identifiant de conteneur valide. Il ne
peut jamais contenir une commande libre.

L'identite operationnelle d'une cible est le triplet :

```text
(driver, connection_id, target)
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
  -> conteneur running
  -> readiness check reussi
  -> job succeeded
  -> service on
```

Pour un arret :

```text
commande acceptee
  -> conteneur stopped
  -> job succeeded
  -> service off
```

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

Valeurs initiales envisagees, a confirmer pendant l'implementation :

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
- `service_targets`, qui associe au plus une cible a un service et porte le type
  de readiness check `docker_state`, `docker_health`, `http` ou `tcp` ;
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
