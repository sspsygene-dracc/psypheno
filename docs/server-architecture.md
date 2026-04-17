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
| **Dev** | 3112 | https://psypheno-dev.gi.ucsc.edu | `sspsygene-dev.service` | `sspsygene_website_dev` |
| **Internal** | 3111 | https://psypheno-int.gi.ucsc.edu | `sspsygene-int.service` | `sspsygene_website_int` |

**Key points:**

- **All three instances are independent.** Each has its own code checkout
  and database on `/hive`. Deploys to one do not affect the others. Each
  instance has its own deploy script: `deploy-prod.sh`, `deploy-dev.sh`,
  `deploy-int.sh`.
- **Internal (int)** is password-protected via Apache basic auth and intended
  for consortium-internal, pre-publication data.
- **No sudo for data updates.** The web process auto-detects a rebuilt
  SQLite file (inode/mtime check in `web/lib/db.ts`) and re-opens the
  connection on the next query, so wranglers running `./deploy-*.sh --load-db`
  do not need to restart the service. Pass `--restart` (requires sudo) only
  when JS code changes need to be picked up.

## Directory Layout

Data directories live on `/hive` (a shared filesystem accessible from both
hgwdev and psygene). They were **not** moved to local disk on psygene — the
`/data/sspsygene_website/` directory on psygene, if it still exists, is an
unused leftover from an earlier configuration.

```
/hive/groups/SSPsyGene/
  sspsygene_website/              ← Production
    data/
      datasets/                   ← Dataset configs + data files
      homology/                   ← Gene reference files
      db/sspsygene.db             ← SQLite database
    processing/                   ← Python processing pipeline
    web/                          ← Next.js web application
  sspsygene_website_dev/          ← Dev (separate copy, same structure)
  sspsygene_website_int/          ← Internal (separate copy, same structure)
```

There is also a symlink `/cluster/home/jbirgmei/sspsygene_website` →
`/hive/groups/SSPsyGene/sspsygene_website`. The prod systemd service file uses
the `/cluster/home/...` path; dev and int reference their `/hive/...` paths
directly.

### Systemd service configuration

All three service files live in `/etc/systemd/system/` on psygene:

**sspsygene.service (prod):**
```ini
ExecStart=/usr/bin/npm start -- --port 3110
WorkingDirectory=/cluster/home/jbirgmei/sspsygene_website/web
User=jbirgmei
Environment=SSPSYGENE_DATA_DB=/cluster/home/jbirgmei/sspsygene_website/data/db/sspsygene.db
Environment=NODE_ENV=production
Restart=always
```

**sspsygene-dev.service (dev):**
```ini
ExecStart=/usr/bin/npm start -- --port 3112
WorkingDirectory=/hive/groups/SSPsyGene/sspsygene_website_dev/web
User=jbirgmei
Environment=SSPSYGENE_DATA_DB=/hive/groups/SSPsyGene/sspsygene_website_dev/data/db/sspsygene.db
Environment=NODE_ENV=production
Restart=always
```

**sspsygene-int.service (int):**
```ini
ExecStart=/usr/bin/npm start -- --port 3111
WorkingDirectory=/hive/groups/SSPsyGene/sspsygene_website_int/web
User=jbirgmei
Environment=SSPSYGENE_DATA_DB=/hive/groups/SSPsyGene/sspsygene_website_int/data/db/sspsygene.db
Environment=NODE_ENV=production
Restart=always
```

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

Each instance has its own deploy script run directly on psygene (or hgwdev):

```bash
# In each site's root directory (/hive/groups/SSPsyGene/sspsygene_website*/):
./deploy-prod.sh                       # pull code only, no DB rebuild, no restart
./deploy-prod.sh --load-db             # pull + rebuild DB (wrangler workflow; no sudo)
./deploy-prod.sh --restart             # pull + restart service (needs sudo; for code deploys)
./deploy-prod.sh --load-db --restart   # full deploy

# Same flags for ./deploy-dev.sh and ./deploy-int.sh.
```

**Default is no restart.** The web process auto-detects a rebuilt SQLite
file (inode/mtime check in `web/lib/db.ts`) and re-opens the connection on
the next query. Wranglers updating data therefore never need sudo. The
Python `load-db` pipeline builds the new DB at `sspsygene.db.new` and
atomically swaps it in (`sq_load.py`), so readers never observe a missing
or half-written file.

Pass `--restart` (requires sudo) only when JS code has changed and needs to
be reloaded.

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
- **Apr 2026:** Dev instance moved to its own directory (`sspsygene_website_dev`)
  so dev deploys no longer affect prod. Web process gained a file-change check
  so wrangler data updates (`./deploy-*.sh --load-db`) no longer require a
  sudo systemctl restart; the Python pipeline switched to atomic rename for
  safe hot-swapping.
