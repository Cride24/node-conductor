NodeConductor/
  README.md
  README.fr.md
  LICENSE
  .gitignore

  docs/
    arborescence.md
    architecture.md
    api.md
	cahier-des-charges.md
    decisions/
      ADR-0001-tech-stack.md

  shared/
    openapi/
      openapi.snapshot.json        # export figé pour bot/front (optionnel)
    contracts/
      events.md                    # types d'événements, severities, etc.
      roles.md                     # rôles & permissions (source de vérité)
    schemas/
      discord_channels.json        # exemples/config (optionnel)

  backend/
    pyproject.toml
    src/nodeconductor/
      main.py
      api/
        routes/
          auth.py
          health.py
          services.py
          machines.py
          containers.py
          bot.py
          events.py
        deps.py
      core/
        config.py                  # env, settings
        security.py                # hash, jwt, roles
        logging.py                 # logs structurés
      db/
        session.py
        models/
          user.py
          machine.py
          service.py
          job.py
          event.py
          discord.py
        migrations/                # Alembic
      connectors/
        proxmox.py
        docker.py
        power_wol.py
        power_ssh.py
        discord_link.py            # handshake/heartbeat bot
      services/
        orchestrator.py            # logique start/stop, verrous
        jobs_worker.py             # worker MVP
        state_collector.py         # refresh états
      tests/
        test_auth.py
        test_services.py
        test_jobs.py

  frontend/
    package.json
    vite.config.ts
    src/
      app/
      pages/
        Dashboard.tsx
        Services.tsx
        Machines.tsx
        Containers.tsx
        Bot.tsx
        Users.tsx
        Events.tsx
      components/
      api/
        client.ts                  # wrapper fetch + tokens
        types.ts                   # types générés openapi (optionnel)
      i18n/
        fr.json
        en.json

  bot/
    package.json
    src/
      index.ts
      config.ts
      api/
        orchestratorClient.ts
      discord/
        commands.ts                # mention parsing
        voice.ts                   # présence vocale
        channelsSync.ts            # sync salons
        heartbeat.ts               # heartbeat vers backend
      security/
        allowlist.ts               # filtrage user_id/role_id
      tests/

  deploy/
    docker/
      compose.yml
      .env.example
    proxmox/
      proxmox-compose.sh
      templates/                   # snippets cloud-init ou conf LXC
      vars.example.env

  scripts/
    dev.sh
    lint.sh
    format.sh