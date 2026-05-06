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

## Testing

There is no CI. The contract is `scripts/test.sh` — run it before you push.

```bash
scripts/test.sh             # fast suites (default) — always safe to run
scripts/test.sh all         # everything, including e2e and data-corr
scripts/test.sh python      # pytest unit only
scripts/test.sh web         # tsc --noEmit + vitest
scripts/test.sh e2e         # playwright (needs a dev server on :3000)
scripts/test.sh data-corr   # data-correspondence (needs the built DB)
```

The script fails fast: it stops at the first failing suite and prints the
exact one-liner to re-run just that suite.

### What's in each suite

| Suite       | What runs                                              | Time    | Prereqs |
|-------------|--------------------------------------------------------|---------|---------|
| `python`    | `pytest processing/tests` (excl. `data_correspondence`) | ~10–20s | `data/homology/` payload (or `$SSPSYGENE_TEST_HOMOLOGY_DIR`) |
| `web`       | `tsc --noEmit` + `vitest run`                          | ~10s    | `web/node_modules/` (run `npm install` once) |
| `e2e`       | `playwright test`                                      | ~10s    | dev server on `:3000` (`cd web && npm run dev`) |
| `data-corr` | `pytest processing/tests/data_correspondence`          | ~5s     | `data/db/sspsygene.db` (`sspsygene load-db`) |
| `fast`      | `python` + `web`                                       | ~30s    | union of above |
| `all`       | everything                                             | ~50s    | dev server + built DB |

The `e2e` suite deliberately does **not** spawn its own dev server — it
probes `localhost:3000` and refuses with a clear message if nothing
answers, so it doesn't fight whatever you have running. Same idea for
`data-corr`: it refuses if the SQLite file is missing rather than letting
pytest crash deep inside a fixture.

### When to run what

- **Before every commit:** `scripts/test.sh` (fast). If you only touched
  Python, `scripts/test.sh python` is fine; same for `web`.
- **Before merging UI-touching changes:** also `scripts/test.sh e2e` —
  type checks and unit tests don't catch render or routing regressions.
- **Before merging dataset-preprocessing changes** (anything under
  `data/datasets/*/preprocess.py`, `processing/src/processing/preprocessing/`,
  or the `load-db` pipeline that affects loaded values): also
  `scripts/test.sh data-corr`. Useful as an occasional periodic check
  even when you didn't touch preprocessing — drift in upstream data can
  break it.
- **Before deploys:** `scripts/test.sh all`.

### Why there's no CI

Deliberate. The team is small (one full-time developer, a few wranglers),
the repo is public so cost isn't the issue — the reason is operational
simplicity: one entry point on the developer's machine is easier to
reason about than a separate CI environment that has to mirror local
setup (Python venv, R, payload data, the gitignored homology files).

If we ever want CI, `scripts/test.sh` is already the contract: a single
GitHub Actions workflow that checks out the repo, restores the venv and
homology payload, and calls `scripts/test.sh` is all that's needed.

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
    --instances dev,int,prod           Comma-separated subset of instances
                                         (order ignored; always rolls
                                         dev → int → prod). Default: all three.
    --load-db                          Rebuild DB during deploy
    --preprocess                       Re-run each dataset's preprocess.py
                                         on the selected sites before load-db
    --run-tests                        Run scripts/test.sh all on each
                                         selected site after build/load-db
                                         (python + web + data-corr incl. slow
                                         + playwright e2e against the deployed
                                         URL). Hard-aborts before restart on
                                         first failure.
    --no-push                          Skip git push
    --restart                          Restart web servers (default: no restart;
                                         web auto-detects DB changes)

  load-gene-descriptions             Build gene_descriptions.db from NCBI data
```
