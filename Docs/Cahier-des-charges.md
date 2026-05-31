# Cahier des charges — CubeGuardian v2

## 1) Vision & philosophie

CubeGuardian v2 est un **orchestrateur d’infrastructure orienté services**, conçu pour piloter simplement et sûrement :
- des **machines** (physiques ou virtuelles),
- des **conteneurs** (Proxmox LXC/VM et Docker),
- un **bot Discord** servant d’interface alternative,
- avec **monitoring, règles, notifications et sécurité intégrés dès le départ**.

L’orchestrateur est le **cerveau unique**.
Tous les points d’entrée (UI, bot, futur LLM, API externe) **passent par lui**.

---

## 2) Objectifs

### 2.1 Objectifs fonctionnels
- Piloter ON/OFF machines et conteneurs.
- Connaître l’état en temps réel de :
  - machines
  - conteneurs
  - orchestrateur
  - bot Discord
- Regrouper l’infrastructure en **services logiques** (ex : “Steampunk”).
- Appliquer des **règles de démarrage / arrêt** fiables.
- Notifier les utilisateurs (UI, Discord, e-mail).
- Permettre le contrôle via :
  - interface web sécurisée
  - bot Discord (commandes + présence vocale).

### 2.2 Objectifs non fonctionnels
- Sécurité forte dès la v1.
- Robustesse (timeouts, retry, verrous).
- Extensibilité (nouveaux connecteurs, nouveaux bots).
- Déploiement simple et propre (Docker **et** Proxmox natif).

---

## 3) Périmètre

### Inclus (v1)
- Proxmox (LXC + VM).
- Docker (local ou distant).
- Machines ou Apareils ON/OFF (WoL + arrêt).
- Bot Discord (commandes, notifs, présence vocale).
- Interface web complète.
- Authentification + rôles.
- Notifications multi-canaux.

### Hors périmètre (mais anticipé)
- HA multi-orchestrateurs.
- Autoscaling avancé.
- Monitoring type Grafana.
- Scheduling avancé (cron) → structure prévue.

---

## 4) Concepts clés

- **Machine** : hôte physique ou VM support.
- **Conteneur** :
  - Proxmox (node + vmid)
  - Docker (host + name/id)
- **Service** : groupe logique pilotable (machines + conteneurs + règles).
- **Bot Discord** : point d’entrée/sortie optionnel, piloté par l’orchestrateur.

---

## 5) Architecture cible

### 5.1 Composants
1. Orchestrateur (API + UI)
2. Bot Discord
3. Base de données (PostgreSQL recommandé)
4. Connecteurs :
   - Proxmox
   - Docker
   - Power (WoL / SSH / IPMI)
   - Notifications (Discord / Email / UI)

### 5.2 Principes
- API = source de vérité.
- Actions start/stop = jobs asynchrones.
- Aucune logique infra dans le bot.
- Tous les événements sont journalisés.

Detail de conception : voir `Docs/Jobs-et-actions.md` pour le modele de jobs, les etats transitoires, la protection contre les demandes concurrentes et le cas d'usage LLM.
Voir aussi `Docs/Logs-et-evenements.md` pour la separation entre jobs, events, audit et debug configurable.
Les regles de decoupage et de lisibilite du code sont posees dans `Docs/Regles-de-code.md`.

---

## 6) Gestion de l’état global

### 6.1 Entités surveillées
- Machines
- Conteneurs Proxmox
- Conteneurs Docker
- Orchestrateur
- Bot Discord

### 6.2 États possibles
`ON | OFF | STARTING | STOPPING | DEGRADED | UNKNOWN | ERROR`

Pour chaque entité :
- état courant
- dernier changement
- dernier check
- message/cause optionnelle

### 6.3 Health Orchestrateur
Endpoint `/health` :
- DB OK/KO
- connecteurs OK/KO
- version
- uptime

---

## 7) Bot Discord (entité de première classe) [i18n-ready]

### 7.1 Health & monitoring
Le bot expose un heartbeat vers l’orchestrateur :
- connecté à Discord (oui/non)
- latence API
- serveurs accessibles
- salon notifications atteignable
- présence vocale active (oui/non)
- timestamp dernier heartbeat

Absence de heartbeat → `UNKNOWN` puis `ERROR`.

### 7.2 Configuration (UI dédiée)
Écran **Bot Discord** :
- état + heartbeat
- token (secret, jamais en clair)
- serveurs (guilds) autorisés
- intents requis
- salon de notifications
- salons vocaux surveillés
- bouton “notification de test”
- logs récents

### 7.3 Synchronisation des salons
- À la connexion :
  - récupération salons texte + vocaux
  - stockage en DB (guild_id, channel_id, name, type)
- Écoute des événements Discord :
  - création / suppression / renommage de salon
  - mise à jour automatique de la DB
- Fallback :
  - bouton “Synchroniser salons”
  - sync périodique configurable

---

## 8) Sécurité Discord & filtrage utilisateurs

### 8.1 Commandes par mention
Format :
@CubeGuardian démarre steampunk
@CubeGuardian statut
@CubeGuardian aide

### 8.2 Filtrage utilisateurs
- Autorisation par :
  - user_id Discord (principal)
  - rôle(s) Discord (optionnel)
- UI :
  - liste “utilisateurs récemment vus”
  - liste “présents en vocal”
  - bouton “ajouter à la whitelist”
- Stockage :
  - ID Discord comme vérité
  - pseudo = indicatif

### 8.3 Présence vocale (trigger)
Par service :
- salon vocal surveillé
- whitelist utilisateurs
- seuil minimum X
- temporisation arrêt Y minutes
- cooldown anti yo-yo

---

## 9) Services & règles

### 9.1 Service
Un service regroupe :
- conteneurs Proxmox
- conteneurs Docker
- machines requises
- règles
- canaux de notification

### 9.2 Règles de démarrage
Exemple :
1. Vérifier machine ON → WoL si nécessaire
2. Attendre disponibilité
3. Démarrer conteneurs
4. Vérifier état final
5. Notifier

### 9.3 Règles d’arrêt
- arrêt conteneurs
- extinction machine si plus utilisée
- notification

Verrou obligatoire par service.

---

## 10) Notifications

### Canaux
- UI (centre de notifications)
- Discord
- Email

### Événements
- start/stop demandé
- succès / échec
- timeout
- perte de contact
- erreur bot
- erreur orchestrateur

Préférences par service et par utilisateur.

---

## 11) Interface Web [i18n-ready]

### 11.1 Auth & bootstrap
- Si aucun utilisateur :
  - écran création admin
  - désactivé après succès

### 11.2 Rôles
- SUPER_ADMIN
- ADMIN
- OPERATOR
- VIEWER

### 11.3 Écrans
1. Dashboard
2. Services
3. Machines
4. Conteneurs
5. Règles & triggers
6. Notifications
7. Utilisateurs & sécurité
8. Bot Discord

---

## 12) API (indicatif)

- Auth
- Services (CRUD + start/stop)
- Machines / conteneurs (CRUD)
- Events
- Health

---

## 13) Modèle de données (simplifié)

- User
- Machine
- ProxmoxHost / ProxmoxContainer
- DockerHost / DockerContainer
- Service
- Rule / Trigger
- DiscordBotConfig
- DiscordChannel
- DiscordUserWhitelist
- Event

Secrets stockés hors DB.

---

## 14) Déploiement

### Mode A — Docker Compose
- `docker-compose.yml`
- orchestrateur
- bot
- postgres
- proxy optionnel

### Mode B — Proxmox natif
- script `proxmox-compose.sh`
- LXC/VM séparés :
  - orchestrateur
  - bot
  - DB
- pas de Docker dans LXC par défaut

Objectif : une UX similaire à “stack up”.

---

## 15) Robustesse & qualité

- Jobs asynchrones
- Timeouts configurables
- Retry contrôlé
- Logs structurés
- Historique consultable
- Mode dégradé sans crash

Pour les actions de pilotage, l'API doit enregistrer une demande sous forme de job, puis laisser un worker executer l'action. Cela evite qu'un client web, Discord ou LLM puisse enchainer des actions contradictoires sans controle d'etat.

Les jobs actifs servent au controle d'execution. Les futurs events serviront a l'historique metier, a l'audit et a la surveillance, afin que les jobs termines puissent plus tard etre archives ou nettoyes sans perdre l'histoire utile.

---

## 16) Critères d’acceptation v1

- Création admin au premier lancement
- Déclaration machines + conteneurs
- Création service “Steampunk”
- Start/stop depuis UI
- Start/stop depuis Discord
- Notifications reçues
- Présence vocale fonctionnelle
- Bot visible et monitoré dans l’UI

---

## 17) Évolutions prévues

- Planning (cron) par service.
- Dépendances avancées entre services (ordre strict, healthchecks applicatifs).
- Multi-environnements (maison / pro / lab).
- Autres bots / connecteurs spécialisés (LLM, outils externes, etc.).
- IA assistante pour l’orchestration et le diagnostic.
- **Internationalisation (i18n) et traduction multi-langues** :
  - Interface web traduite (au minimum EN / FR au départ).
  - Messages du bot Discord traduisibles.
  - Notifications (UI, Discord, email) basées sur la langue utilisateur.
  - Architecture prévue dès le départ (fichiers de traduction, clés, fallback).

---
