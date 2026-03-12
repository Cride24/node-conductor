NodeConductor — Orchestrateur d’infrastructure (UI Web + Bot Discord)

Ce projet est destiné à mon apprentissage en programmation. Il est donc possible que le code soit peu optimisé et que les choix de design soient peu judicieux. Tout commentaire bienveillant et constructif est le bienvenue.

NodeConductor est un **orchestrateur d’infrastructure orienté services**. Il centralise toute la logique (API + UI) et pilote :

- des **machines** (physiques ou VM support),
- des **conteneurs Proxmox** (LXC/VM),
- des **conteneurs Docker** (local ou distant),
- un **bot Discord** (commandes, notifications, présence vocale),
  avec **monitoring, règles, notifications et sécurité** pensés dès le départ.

Principe clé : **l’API de l’orchestrateur est la source de vérité**. Le bot Discord ne contient aucune logique “infra” : il appelle l’orchestrateur.

---

[English: README.md](README.md)

---

Périmètre (v1)

Inclus :

- Proxmox (LXC + VM)
- Docker (local ou distant)
- Machines ON/OFF (Wake-on-LAN + arrêt)
- Interface web complète + authentification + rôles
- Bot Discord (commandes par mention, notifications, présence vocale)
- Notifications multi-canaux : UI, Discord, e-mail

Hors périmètre (anticipé) :

- HA multi-orchestrateurs
- Autoscaling avancé
- Monitoring Grafana-like
- Scheduling avancé (cron) : structure prévue

---

Concepts

- Machine : hôte physique ou VM support.
- Conteneur :
  - Proxmox : (node + vmid)
  - Docker : (host + name/id)
- Service : groupe logique pilotable (machines + conteneurs + règles + canaux de notification).
- États (pour chaque entité) : ON | OFF | STARTING | STOPPING | DEGRADED | UNKNOWN | ERROR

---

Architecture cible (résumé)

Composants :

1. Orchestrateur (API + UI)
2. Bot Discord
3. Base de données (PostgreSQL recommandé)
4. Connecteurs : Proxmox, Docker, Power (WoL/SSH/IPMI), Notifications (Discord/Email/UI)

Principes :

- Les actions start/stop sont des **jobs asynchrones**.
- Verrou obligatoire par service (anti “yo-yo” / concurrence).
- Tous les événements sont journalisés (logs + historique consultable).

Endpoint de health (indicatif) :

- `/health` : DB OK/KO, connecteurs OK/KO, version, uptime

---

Sécurité & rôles (UI)

Bootstrap :

- Au premier lancement, si aucun utilisateur n’existe : écran de création de l’admin (désactivé après succès).

Rôles :

- SUPER_ADMIN, ADMIN, OPERATOR, VIEWER

Discord :

- Commandes par mention (ex. “@NodeConductor statut”, “@NodeConductor démarre steampunk”).
- Filtrage par user_id (principal) et/ou rôles Discord (optionnel).
- Configuration bot dans l’UI : token (secret, jamais en clair), guilds autorisées, salons, heartbeat, sync des salons, bouton “notification de test”, logs récents.

---

Critères d’acceptation (v1)

- Création admin au premier lancement
- Déclaration machines + conteneurs
- Création d’un service “Steampunk”
- Start/stop depuis l’UI
- Start/stop depuis Discord
- Notifications reçues (UI/Discord/email selon config)
- Présence vocale fonctionnelle
- Bot visible et monitoré dans l’UI

---

Documentation

- Cahier des charges : `Cahier-des-charges.md`
- Arborescence/structure cible : `Docs/Arborescence.md`

---

Méthode de travail & outils

- **Objectif de ce dépôt** : il s’agit d’un projet d’apprentissage. La priorité est de construire de bonnes habitudes (architecture, lisibilité, petites itérations) plus que d’avoir un code “parfait”.
- **Workflow sur une fonctionnalité** :
  - compréhension du besoin et rédaction d’un court plan,
  - conception simple de l’architecture ou des flux de données,
  - implémentation par **petites étapes relisables**,
  - exécution de **tests manuels** (scénario principal + quelques cas limites),
  - prise de notes sur ce qui doit être refactoré ou testé plus tard.
- **Éditeur & outils** :
  - j’utilise **Cursor** comme éditeur principal, avec **autocomplétion/IntelliSense** pour accélérer la saisie et limiter les erreurs de syntaxe,
  - j’utilise parfois un **mode “mentor IA”** pour obtenir des explications, des pistes de design ou des suggestions de refactorings, mais je relis et j’adapte toujours le code moi-même.
- **Politique d’assistance (IA / autocomplétion)** :
  - pas de copier/coller aveugle de gros fichiers générés,
  - priorité à la compréhension de ce qui est écrit, même lorsqu’il y a assistance,
  - priorité à la clarté et à une architecture explicite plutôt qu’aux “one-liners” mal lisibles.

Niveau de qualité (actuel → objectif)

- **Actuel** :
  - tests manuels (scénarios de base),
  - relecture personnelle des changements (naming, structure, cas évidents),
  - documentation de l’intention dans `Docs/` quand c’est pertinent.
- **Objectif (progressif)** :
  - ajouter formatage et linting (par exemple Prettier, ESLint) avec des scripts npm clairs,
  - introduire des tests unitaires/d’intégration sur les services critiques,
  - définir une petite checklist pour les nouvelles fonctionnalités (tests faits, docs mises à jour, contraintes identifiées),
  - éventuellement ajouter plus tard une CI pour exécuter lint/tests automatiquement.

---

Déploiement (prévu)

Mode A — Docker Compose :

- orchestrateur + bot + postgres (proxy optionnel)

Mode B — Proxmox natif :

- script `proxmox-compose.sh`
- LXC/VM séparés : orchestrateur, bot, DB
