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

- **Each instance has its own code checkout and database on `/hive`.** Code
  deploys to one do not affect the others.
- **The dataset DB is built once, on dev (#225).** dev is the build superset:
  it holds every dataset. prod's and int's DBs are *derived* from dev's by
  `sspsygene subset-db` at promotion time, restricted to the datasets whose
  `deployTo` names that instance. No other instance ever runs `load-db` — see
  **Build once, subset at promotion** below.
- **Dev (dev)** is the staging instance for **prod**. Public datasets and code
  changes land on dev first, get verified, then go to prod.
- **Internal (int)** is a parallel site for embargoed / pre-publication
  datasets, password-protected via Apache basic auth. Its dataset set may be
  disjoint from prod's — embargoed data may never go to prod, and prod's public
  datasets aren't necessarily on int. int does not promote to prod; both int
  and prod are promoted *from dev*.
- **No sudo for data updates.** The web process auto-detects a rebuilt
  SQLite file (inode/mtime check in `web/lib/db.ts`) and re-opens the
  connection on the next query, so a promotion needs no service restart. Code
  deploys (JS changes) still require a restart, handled via the
  `sspsygene deploy` CLI from a developer laptop.

## Build once, subset at promotion (#225)

Every dataset's `config.yaml` declares a mandatory `deployTo` list naming the
instances it may be served on (`dev` always; `int` and `prod` independently
optional). That declaration — not which payloads someone happened to rsync —
is what decides where a dataset appears.

```
  dev            sspsygene load-db          → sspsygene.db          (superset)
                 sspsygene meta-analysis    → sspsygene-meta.db     ┐ prod-labelled
                 sspsygene overview-matrix  → sspsygene-overview.db ┘ inputs only

  promote        subset-db --destination prod  → sspsygene-prod.db  (on dev)
   dev → prod    verify-destination            → abort on any finding
                 cp main + meta + overview     → prod/*.new
                 verify staged main DB         → abort on any finding
                 mv all three                  → atomic swap
                 verify prod after the swap

  promote        the same, with --destination int
   dev → int
```

Why it is shaped this way:

- **Subsetting is fail-closed.** `subset-db` creates an empty DB and copies in
  only what the labels allow. It is deliberately not `cp` + `DELETE`: that
  starts prod's file as a byte copy of the embargoed superset, ships anything
  added later until someone extends the deletion list, and without a completed
  `VACUUM` leaves the deleted rows physically present in a file we serve for
  download.
- **The meta and overview DBs are copied verbatim, not subsetted.** Both are
  computed from `prod`-labelled inputs only, so the same bytes are correct on
  every instance. Rebuilding them per site would also miss the entire R cache,
  which keys on the p-value bytes.
- **A dev-only dataset does not appear in dev's `/most-significant` or
  `/matrix`.** Accepted tradeoff: it is the price of computing those once.
- **`verify-destination` is an independent check.** It re-reads `deployTo` from
  the target checkout's configs, cross-checks that against the DB's own
  `dataset_destinations`, and deny-scans every place a table name can hide
  (including the member list inside `all-tables.zip`). Run it against any live
  instance at any time:

  ```bash
  sspsygene verify-destination \
      /hive/groups/SSPsyGene/sspsygene_website/data/db/sspsygene.db \
      --destination prod
  ```

  On any finding a promotion aborts, leaves the target untouched, exits
  non-zero, and prints a banner. There is no `--force`.

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
      db/sspsygene.db             ← dataset DB (subsetted from dev's)
      db/sspsygene-meta.db        ← combined p-values (copied from dev)
      db/sspsygene-overview.db    ← overview matrix (copied from dev)
    processing/                   ← Python processing pipeline
    web/                          ← Next.js web application
  sspsygene_website_dev/          ← Dev — the build server; same structure,
                                    plus the sspsygene-{int,prod}.db files
                                    subset-db stages before a promotion
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

Three distinct paths:

**Data-only updates on dev (wranglers, on the server, no sudo).** `cd` into
`sspsygene_website_dev`, set the `SSPSYGENE_*` environment variables, and run
`sspsygene load-db`. The Python pipeline builds the new DB at
`sspsygene.db.new` and atomically swaps it in (`sq_load.py`), and the running
web process auto-detects the inode/mtime change and re-opens its connection on
the next query. No restart, no sudo. See
[adding-datasets.md](adding-datasets.md) for the full wrangler workflow.

**dev is the only site where this is done.** `sspsygene deploy --load-db` (or
`--preprocess`) against int or prod is refused: since #225 those DBs are
derived from dev's, and an in-place rebuild would need the site's checkout to
hold every dev dataset's gitignored payloads — the thing this design prevents
— while bypassing the destination check entirely.

**Promote dev's build to prod or int (the data path onto either site).** Use
`sspsygene promote-dev-to-prod` or `sspsygene promote-dev-to-int`. Each
subsets dev's superset down to the datasets whose `deployTo` names that
instance, verifies the result before and after the swap, and copies it plus
dev's `sspsygene-meta.db` and `sspsygene-overview.db` into the target's db dir
(issues #178, #225). dev and the targets share `/hive`, so it's a local `cp` +
`mv`; no rebuild, no restart (same inode-swap auto-reload as above). Runs from
a laptop (SSH) or on the server (`--local`). See **Build once, subset at
promotion** above for the full sequence and the reasoning.

**Code deploys (JS changes, from a developer laptop).** Use
`sspsygene deploy` — a Click command in `processing/src/processing/deploy.py`
that handles `git push`, SSH to hgwdev for `git pull` + optional `load-db`
+ `npm run build` per site, and `kill`ing the Next.js processes on psygene
so systemd restarts them with the new build. Target subsets with
`--instances dev,int,prod` (any subset; instances are iterated in
dev→int→prod order but they're independent deploys, not a promotion chain),
rebuild data with `--load-db`, re-run wrangler preprocessing with
`--preprocess`, and pass `--restart` to restart the web servers. See
[development.md](development.md) for the CLI reference.

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
  so wrangler data updates no longer require a sudo systemctl restart; the
  Python pipeline switched to atomic rename for safe hot-swapping. The
  per-instance deploy shell scripts were removed — wranglers use
  `sspsygene load-db` directly, and code deploys go through `sspsygene deploy`.
