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

# Fast end-to-end smoke test (~seconds, exercises every pipeline stage)
sspsygene load-db --test
```

The database is written to `$SSPSYGENE_DATA_DB`. The pipeline reads dataset
configs from `data/datasets/*/config.yaml` and gene homology files from
`data/homology/`.

### Fast iteration with `--test`

`sspsygene load-db --test` runs the **full** pipeline (every dataset, every
link table, meta-analysis, indexing) but restricts each dataset's rows to
those whose gene-keyed columns *all* intersect a bundled fixture of central
genes (top-100 target Fisher + top-100 perturbed Cauchy + perturbed-side
genes from any small perturb-screen link table), then caps each unique
gene-key combination to 200 rows. AND semantics across columns keeps pair
tables tractable; the per-group cap prevents any one (perturbation, target)
combo or any one gene's per-cell-type/age repeats from bloating the build.
Useful for shaking out loader/schema changes end-to-end in ~30 s instead of
2–3 min.

The fixture is `processing/src/processing/test_fixture_genes.json` (committed).
Regenerate it from a current full build with:

```bash
processing/.venv-claude/bin/python processing/scripts/build_test_fixture.py
```

`--test` is orthogonal to `--no-index` and `--skip-meta-analysis` — combine as
needed. Datasets whose tables have empty `gene_mappings` (pure metadata) pass
through unfiltered.

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

This means wranglers updating data just run `sspsygene load-db` on the
server with the right env vars — no restart, no sudo.

## Deployment

Three independent server instances run on psygene, each with its own code
checkout and database on `/hive`:

| Instance | URL | Directory |
|----------|-----|-----------|
| **Internal** | https://psypheno-int.gi.ucsc.edu | `sspsygene_website_int` |
| **Dev** | https://psypheno-dev.gi.ucsc.edu | `sspsygene_website_dev` |
| **Production** | https://psypheno.gi.ucsc.edu | `sspsygene_website` |

Two deployment paths:

- **Data-only updates** (wranglers, run on the server): `git pull` and
  `sspsygene load-db` in the target site's directory with `SSPSYGENE_*`
  env vars pointing at it. The web process auto-detects the new DB file,
  no restart. See [adding-datasets.md](adding-datasets.md).
- **Code deploys** (JS changes, run from your laptop): `sspsygene deploy`
  orchestrates `git push`, remote `git pull` + `npm run build` on hgwdev,
  and a kill-to-respawn restart on psygene. See the CLI reference below
  and [server-architecture.md](server-architecture.md) for details.

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
    --test                             Restrict to bundled top-genes fixture

  deploy                             Deploy to prod, dev, and internal sites
    --prod-only / --dev-only / --int-only   Target one environment
    --load-db                          Rebuild DB during deploy
    --no-push                          Skip git push
    --restart                          Restart web servers (default: no restart;
                                         web auto-detects DB changes)

  load-gene-descriptions             Build gene_descriptions.db from NCBI data
```
