# Local Development Setup

## Prerequisites

- Python 3.11+ (via conda)
- Node.js (for the Next.js web app)
- Git

## Python Processing Pipeline

### Install

```bash
conda create -n sspsygene python=3.13
conda activate sspsygene
cd processing
pip install -e .
```

### Environment Variables

```bash
export SSPSYGENE_DATA_DIR="$(pwd)/data"
export SSPSYGENE_CONFIG_JSON="processing/src/processing/config.json"
export SSPSYGENE_DATA_DB="$(pwd)/data/db/sspsygene.db"
```

### Load the Database

```bash
# Load all datasets (full production build, ~15-30 min)
sspsygene load-db

# Load a single dataset (fast, for testing)
sspsygene load-db --dataset my-dataset

# Load all datasets but skip slow steps (for testing)
sspsygene load-db --no-index --skip-meta-analysis
```

The database is written to `$SSPSYGENE_DATA_DB`. The pipeline reads dataset
configs from `data/datasets/*/config.yaml` and gene homology files from
`data/homology/`.

## Web Application

### Install and Run

```bash
cd web
npm install

# Development server (hot-reload)
npm run dev

# Production build
npm run build
npm start
```

The web app reads `SSPSYGENE_DATA_DB` to find the SQLite database. It opens
the database in read-only mode.

Visit `http://localhost:3000` after starting the dev server.

### Database auto-reload

The web process auto-detects when the SQLite database has been rebuilt. On
every request, [web/lib/db.ts](../web/lib/db.ts) runs a cheap `statSync` and
compares the file's inode, mtime, and size against its cached values. When
any of these change (e.g. after the Python `load-db` pipeline atomically
swaps in a new `.db` file via `Path.replace()`), the process closes the old
handle and opens the new file — no service restart needed.

This means `./deploy-*.sh --load-db` works without sudo; pass `--restart`
only when JS code has changed and needs to be reloaded.

## Deployment

Three independent server instances run on psygene, each with its own code
checkout and database on `/hive`:

| Instance | URL | Deploy script | Directory |
|----------|-----|---------------|-----------|
| **Internal** | https://psypheno-int.gi.ucsc.edu | `deploy-int.sh` | `sspsygene_website_int` |
| **Production** | https://psypheno.gi.ucsc.edu | `deploy-prod.sh` | `sspsygene_website` |
| **Dev** | https://psypheno-dev.gi.ucsc.edu | `deploy-dev.sh` | `sspsygene_website_dev` |

Deploy scripts are run directly on the server (hgwdev or psygene):

```bash
# Data-only deploy (no sudo — web auto-detects the new DB):
./deploy-prod.sh --load-db

# Code + data deploy (needs sudo for the service restart):
./deploy-prod.sh --load-db --restart

# Code-only deploy:
./deploy-prod.sh --restart
```

The same `--load-db` / `--restart` flags apply to `deploy-int.sh` and
`deploy-dev.sh`. See [server-architecture.md](server-architecture.md) for
full details.

## CLI Reference

```
sspsygene [--log-level LEVEL] [--log-file PATH] COMMAND

Commands:
  load-db                            Load/rebuild the database
    --dataset TEXT                     Load only this dataset
    --no-index                         Skip index creation
    --skip-meta-analysis               Skip combined p-value computation
    --skip-gene-descriptions           Skip gene description copying
    --skip-missing-datasets            Skip missing input files

  deploy                             Deploy to production and internal sites
    --prod-only / --int-only           Target one environment
    --load-db                          Rebuild DB during deploy
    --no-push                          Skip git push
    --no-restart                       Skip service restart

  load-gene-descriptions             Build gene_descriptions.db from NCBI data
```
