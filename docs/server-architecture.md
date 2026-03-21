# SSPsyGene / Psypheno Web Server Architecture

## Overview

The SSPsyGene project runs a website called **Psypheno** that displays
neuropsychiatric genetics data. Three web server instances run as Node.js
(Next.js) processes on a single machine called **psygene**
(`psygene.gi.ucsc.edu`), managed via systemd. A separate machine called
**hgwdev** is used for building code and loading databases.

## Server Instances

All three instances run on `psygene`, with Apache reverse-proxying each URL
to the corresponding localhost port (with SSL termination).

| Service | Port | URL | systemd unit | Data source |
|---------|------|-----|--------------|-------------|
| **Production** | 3110 | https://psypheno.gi.ucsc.edu | `sspsygene.service` | `sspsygene_website` |
| **Dev** | 3112 | https://psypheno-dev.gi.ucsc.edu | `sspsygene-dev.service` | `sspsygene_website` (same as prod) |
| **Internal** | 3111 | https://psypheno-int.gi.ucsc.edu | `sspsygene-int.service` | `sspsygene_website_int` |

**Key points:**

- **Prod and dev are identical.** They share the same WorkingDirectory and
  database (`sspsygene_website`). The dev instance exists as a separate URL
  for testing convenience, but serves the exact same code and data as prod.
- **Internal (int) is separate.** It has its own code checkout and database
  (`sspsygene_website_int`). It is password-protected via Apache basic auth
  and intended for consortium-internal, pre-publication data.

## Directory Layout

Data directories live on `/hive` (a shared filesystem accessible from both
hgwdev and psygene). They were **not** moved to local disk on psygene — the
`/data/sspsygene_website/` directory on psygene, if it still exists, is an
unused leftover from an earlier configuration.

```
/hive/groups/SSPsyGene/
  sspsygene_website/              ← Production + Dev (shared)
    data/
      datasets/                   ← Dataset configs + data files
      homology/                   ← Gene reference files
      db/sspsygene.db             ← SQLite database
    processing/                   ← Python processing pipeline
    web/                          ← Next.js web application
  sspsygene_website_int/          ← Internal (separate copy)
    (same structure)
```

The systemd service files reference these directories:

- `sspsygene.service` (prod) and `sspsygene-dev.service` (dev):
  `WorkingDirectory=/cluster/home/jbirgmei/sspsygene_website/web`
- `sspsygene-int.service` (int):
  `WorkingDirectory=/hive/groups/SSPsyGene/sspsygene_website_int/web`

The DB path for each instance is configured via the `SSPSYGENE_DATA_DB`
environment variable in the respective systemd service file.

## Machines

### psygene (`psygene.gi.ucsc.edu`)

- Runs all three Next.js web server processes
- Apache handles SSL termination and reverse proxying
- systemd manages service lifecycle (auto-restarts on crash)
- Restart commands: `sudo systemctl restart sspsygene` / `sspsygene-dev` / `sspsygene-int`

### hgwdev

- UCSC internal development/build server
- Used for: `git pull`, `sspsygene load-db`, `npm run build`
- Has access to `/hive` filesystem (where data directories live)
- Conda environment `sspsygene` is installed here for running the Python pipeline

## Deployment Flow

```
Local machine              hgwdev                         psygene
─────────────              ──────                         ───────
git push ──────────────>  git pull (prod + int copies)
                          sspsygene load-db (if needed)
                          npm run build
                                           ──────────>   restart services
                                                         (systemd auto-restart)
```

1. Developer pushes to GitHub from local machine
2. `sspsygene deploy` connects to hgwdev via SSH
3. On hgwdev: pulls latest code, optionally rebuilds DB, runs `npm run build`
4. On psygene: kills running Next.js processes; systemd restarts them
   automatically with the newly built code

### Deploy commands

```bash
# Deploy to production (also updates dev, since they share code)
sspsygene deploy --prod-only [--load-db]

# Deploy to internal only
sspsygene deploy --int-only [--load-db]

# Deploy to both
sspsygene deploy [--load-db]
```

Convenience scripts are also available: `./deploy-prod.sh` and `./deploy-int.sh`.

## Environment Variables

Each instance needs these environment variables (set in systemd service files
on psygene, and passed to `load-db` on hgwdev):

| Variable | Purpose |
|----------|---------|
| `SSPSYGENE_DATA_DIR` | Root data directory (contains `datasets/`, `homology/`, `db/`) |
| `SSPSYGENE_CONFIG_JSON` | Path to `processing/src/processing/config.json` |
| `SSPSYGENE_DATA_DB` | Path to the SQLite database file |

## History

- **Jan 2026:** Three-instance architecture (prod/dev/int) requested by Max
  Haeussler, based on input from the wranglers team.
- **Feb 2026:** William Sullivan initiated the move of web server processes
  from hgwdev to the psygene machine. Cluster admins (Erich) performed the
  migration.
- **Mar 2026:** systemd service configuration finalized by Johannes Birgmeier.
  Data directories remained on `/hive` for backup and hgwdev accessibility
  benefits.
