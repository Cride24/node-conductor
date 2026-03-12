NodeConductor — Infrastructure Orchestrator (Web UI + Discord Bot)

This project is part of my programming learning journey. As a result, the code may not be fully optimized and some design choices may not be ideal. Any kind and constructive feedback is welcome.

NodeConductor is a **service-oriented infrastructure orchestrator**. It centralizes all logic (API + UI) and manages:
- **Machines** (physical hosts or support VMs),
- **Proxmox containers** (LXC/VM),
- **Docker containers** (local or remote),
- a **Discord bot** (commands, notifications, voice presence),
with **monitoring, rules, notifications and security** designed from the start.

Key principle: **the orchestrator API is the source of truth**. The Discord bot contains no "infra" logic: it calls the orchestrator.

---

[Français : README-fr.md](README-fr.md)

---

Scope (v1)

Included:
- Proxmox (LXC + VM)
- Docker (local or remote)
- Machine ON/OFF (Wake-on-LAN + shutdown)
- Full web interface + authentication + roles
- Discord bot (mention commands, notifications, voice presence)
- Multi-channel notifications: UI, Discord, email

Out of scope (planned for later):
- Multi-orchestrator HA
- Advanced autoscaling
- Grafana-like monitoring
- Advanced scheduling (cron): structure planned

---

Concepts

- **Machine**: physical host or support VM.
- **Container**:
  - Proxmox: (node + vmid)
  - Docker: (host + name/id)
- **Service**: logical group that can be operated (machines + containers + rules + notification channels).
- **States** (per entity): ON | OFF | STARTING | STOPPING | DEGRADED | UNKNOWN | ERROR

---

Target Architecture (summary)

Components:
1) Orchestrator (API + UI)
2) Discord bot
3) Database (PostgreSQL recommended)
4) Connectors: Proxmox, Docker, Power (WoL/SSH/IPMI), Notifications (Discord/Email/UI)

Principles:
- Start/stop actions are **asynchronous jobs**.
- Mandatory lock per service (anti "yo-yo" / concurrency).
- All events are logged (logs + consultable history).

Health endpoint (indicative):
- `/health`: DB OK/KO, connectors OK/KO, version, uptime

---

Security & Roles (UI)

Bootstrap:
- On first launch, if no user exists: admin creation screen (disabled after success).

Roles:
- SUPER_ADMIN, ADMIN, OPERATOR, VIEWER

Discord:
- Mention commands (e.g. "@NodeConductor status", "@NodeConductor start steampunk").
- Filtering by user_id (primary) and/or Discord roles (optional).
- Bot configuration in UI: token (secret, never in plain text), allowed guilds, channels, heartbeat, channel sync, "test notification" button, recent logs.

---

Acceptance Criteria (v1)

- Admin creation on first launch
- Machine + container declaration
- Creation of a "Steampunk" service
- Start/stop from UI
- Start/stop from Discord
- Notifications received (UI/Discord/email per config)
- Functional voice presence
- Bot visible and monitored in UI

---

Documentation

- Specifications: `Docs/Cahier-des-charges.md`
- Target structure: `Docs/Arborescence.md`

---

Development workflow & tools

- **Goal of this repository**: this is a learning project. The main objective is to build solid habits (architecture, readability, small iterations) more than “perfect” code.
- **Feature workflow**:
  - understand the problem and write down a short outline,
  - design a simple architecture or data flow,
  - implement in **small, reviewable steps**,
  - run **manual tests** (happy path + a few edge cases),
  - take notes about what should be refactored or tested later.
- **Editor & tooling**:
  - I use **Cursor** as my main editor, with **autocompletion/IntelliSense** to speed up typing and reduce syntax mistakes,
  - I sometimes use an **AI “mentor” mode** to get explanations, alternative designs or refactoring suggestions, but I always review and adapt the code myself.
- **AI / assistance policy**:
  - no blind copy-paste of long generated files,
  - focus on understanding what is written, even when assisted,
  - priority to clarity and explicit architecture over “clever” one-liners.

Quality bar (current → target)

- **Current**:
  - manual tests (basic scenarios),
  - self-review of changes (naming, structure, obvious edge cases),
  - documentation of intent in `Docs/` when relevant.
- **Target (progressively)**:
  - add formatting and linting (e.g. Prettier, ESLint) with clear npm scripts,
  - introduce unit/integration tests on critical services,
  - define a minimal checklist for new features (tests done, docs updated, constraints identified),
  - optionally, add CI later to run lint/tests automatically.

---

Deployment (planned)

Mode A — Docker Compose:
- orchestrator + bot + postgres (optional proxy)

Mode B — Native Proxmox:
- script `proxmox-compose.sh`
- Separate LXC/VM: orchestrator, bot, DB
