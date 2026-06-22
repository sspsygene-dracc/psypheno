# Local Development Setup

## Prerequisites

- Python 3.11+ (via conda)
- Node.js (for the Next.js web app)
- Git

## Python Processing Pipeline

### Install

```bash
# Use Python 3.12 — the pinned pandas==2.2.1 ships no wheel for 3.13, so 3.13
# forces a source build that fails on some machines (numpy/meson build step).
conda create -n sspsygene python=3.12
conda activate sspsygene
cd processing
pip install -e .

# R + the two CRAN packages we need for combined-p-value computation. Pinning
# them inside the conda env (rather than relying on system R) avoids
# libgfortran ABI mismatches between hosts. ACAT isn't on conda-forge —
# `sspsygene load-db` installs it from GitHub into a project-local R lib on
# first run.
conda install -c conda-forge r-base r-poolr r-harmonicmeanp
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
| `e2e`       | `playwright test` (against `:3000`, or `$E2E_BASE_URL`) | ~30s   | dev server on `:3000` (`cd web && npm run dev`), or set `E2E_BASE_URL=https://...` to drive a deployed instance |
| `data-corr` | `pytest processing/tests/data_correspondence`          | ~5s     | `data/db/sspsygene.db` (`sspsygene load-db`) |
| `fast`      | `python` + `web`                                       | ~30s    | union of above |
| `server`    | everything except `e2e` (`python` + `web` + `data-corr`) | ~30s  | built DB. Used by `sspsygene deploy --run-tests` on psygene, where playwright browsers aren't installed. |
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

- **From your laptop (preferred):** `sspsygene deploy` orchestrates
  `git push`, remote `git pull` on hgwdev, optional `load-db`, optional
  preprocessing rerun, optional `npm install` + `npm run build` (only with
  `--build`), and an optional kill-to-respawn web restart on psygene
  (implicit with `--build`, otherwise off). The three instances are
  independent (dev stages prod's public datasets; int is a parallel site
  for embargoed data); when multiple `--instances` are passed they're
  iterated in dev→int→prod order for log clarity, but they don't gate
  each other.

  **Prerequisite (one-time, per psygene user):** miniconda/anaconda must
  be installed at one of the paths the deploy script's `CONDA_INIT` looks
  for. In order, it tries:
  1. `$HOME/opt_rocky9/miniconda3/`
  2. `$HOME/miniconda3/`           (the default `Miniconda3-...-Linux-x86_64.sh` install path)
  3. `$HOME/anaconda3/`
  4. `/opt/conda/`

  The first one that has `etc/profile.d/conda.sh` is sourced. If your
  install lives elsewhere, either symlink it into one of those locations
  or add your path to the list in
  [processing/src/processing/deploy.py](../processing/src/processing/deploy.py).
  Within that env, you need a conda env named `sspsygene` with the same
  Python + R packages as the local install (see *Install* above).
  It works for both data-only updates (`--load-db` and/or `--preprocess`,
  no service restart needed because the web process auto-detects DB
  inode/mtime changes) and code deploys (`--build`, which implies a
  service restart so the new build ID is served). Examples:
  - `sspsygene deploy --instances dev --load-db` — push + pull on dev +
    rebuild dev DB. **This is the wrangler default flow.** No `npm run
    build`, no restart.
  - `sspsygene deploy --instances dev --preprocess --load-db` — also
    re-run each dataset's `preprocess.py` on dev before rebuilding (use
    when a `preprocess.py` change has landed and cleaned data files on
    the server are stale).
  - `sspsygene deploy --instances dev --build` — pull + `npm install` +
    `npm run build` + restart the web service. Use only when JS/TS code
    under `web/` has changed. Wranglers don't typically run this — leave
    it to whoever is touching the web/ code.

  **Why `--build` is off by default:** `npm run build` mints a fresh
  Next.js build ID; without a follow-up restart the running service
  keeps serving HTML that references the OLD build ID's manifest files,
  which the new build just overwrote on disk, producing 404s on
  `_buildManifest.js` and a stuck "Loading…" UI. The implicit restart
  is what avoids that, and the restart only works cleanly for the user
  who owns the systemd unit (currently `jbirgmei`) — so the safe
  default for wranglers is to not touch the build at all.

  See the CLI reference below and the wrangler-facing recipe in
  [adding-datasets.md](adding-datasets.md) → Step 7.

- **Pushing data files:** the server-side `git pull` only carries tracked
  files, so a dataset's gitignored data payloads (raw downloads + cleaned
  `<table>.tsv`) must be pushed separately with `sspsygene rsync-dataset
  <name> --instance dev` *before* the deploy's `load-db`, or that load-db
  fails on a missing `in_path`. `rsync-dataset` pushes only the gitignored
  files (so the server git tree stays clean), creates the remote dir if
  missing, and preserves group-write. The usual wrangler sequence is
  `git push` → `sspsygene rsync-dataset <name> --instance dev` → `sspsygene
  deploy --instances dev --load-db`, all from the laptop.

- **Manually on the server (fallback):** SSH to psygene, `cd` into the
  target site's directory, set the `SSPSYGENE_*` env vars for that site,
  and run `sspsygene load-db`. The web process auto-detects the new DB
  file, no restart. Use this when `sspsygene deploy` isn't available or when
  you want to do exactly one step and nothing else.

- **Promote a verified dev build to prod (no rebuild):** once dev serves a
  build you've verified, `sspsygene promote-dev-to-prod` copies dev's
  already-built `sspsygene.db` (and, by default, `sspsygene-meta.db`) into
  prod's db dir and atomically swaps them in — so prod serves *byte-identical*
  bytes instead of independently re-running preprocess/`load-db` and risking
  drift from gitignored-payload skew or tool/version differences (issue #178).
  dev and prod share the `/hive` filesystem, so the copy is a local `cp` + `mv`
  on the server — no cross-host rsync. **No restart needed** (the web process
  re-opens on the new inode, exactly as after `load-db`/`meta-analysis`), which
  makes it multi-user-safe — unlike `deploy --restart`, it has no systemd/kill
  interaction. It runs from a laptop (SSHes into psygene) or directly on
  hgwdev/psygene (`--local`, or auto-detected by whether the `/hive` trees are
  visible locally). **int is never a source or target** — it carries its own,
  possibly-embargoed dataset set. Before copying it smoke-checks dev's DB
  (exists + non-empty `data_tables`) and after the swap confirms prod's row
  count matches dev's. `--no-meta-analysis` copies only the main DB;
  `--dry-run` previews without writing.

  This is the **standard way to update prod**: prefer it over
  `sspsygene deploy --instances prod --load-db`, which rebuilds the DB on prod
  independently of dev. To steer you there, `deploy` warns and prompts for
  confirmation when you target prod with a DB rebuild (`--load-db` /
  `--preprocess`). A code-only prod deploy (`--build`, no DB rebuild) isn't
  affected — promotion only moves DBs, not code.

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
    --no-r-cache                       Bypass processing/r-cache and re-run
                                         every R meta-analysis job
    --export-only                      Skip the rebuild; only regenerate the
                                         user-facing download blobs
                                         (export_files) inside the existing DB
    --test                             Restrict to bundled top-genes fixture

  deploy                             Deploy to prod, dev, and internal sites
    --instances dev,int,prod           Comma-separated subset of instances
                                         (order ignored; iterated in
                                         dev→int→prod order). Note: the three
                                         sites are independent (dev stages
                                         prod; int is a parallel site for
                                         embargoed data), not a staging chain.
                                         Default: all three.
    --load-db                          Rebuild DB during deploy
    --preprocess                       Re-run each dataset's preprocess.py
                                         on the selected sites before load-db
    --run-tests                        After each site's build/load-db,
                                         restart (if requested), then run
                                         `scripts/test.sh server` on psygene
                                         (python + web-tsc + web-unit +
                                         data-corr) followed by
                                         `scripts/test.sh e2e` LOCALLY against
                                         that site's URL. Hard-aborts on the
                                         first failure.
    --no-push                          Skip git push
    --build / --no-build               Run `npm install` + `npm run build`
                                         on each selected site. Default OFF.
                                         Pass --build only when JS/TS under
                                         web/ has changed. Implies --restart.
    --restart / --no-restart           Kill-and-respawn the npm processes for
                                         the selected instances. Default
                                         tracks --build (on if building, off
                                         otherwise). Only works for the user
                                         whose systemd unit owns the npm
                                         process — currently jbirgmei. Other
                                         wranglers' restart silently no-ops.

  promote-dev-to-prod                Copy dev's built DB file(s) to prod and
                                       atomically swap them in (no rebuild, no
                                       restart). The standard way to update
                                       prod. Runs from a laptop (SSH) or on
                                       hgwdev/psygene (--local). int is never a
                                       source/target. (issue #178)
    --include-meta-analysis /          Also copy sspsygene-meta.db. ON by
      --no-meta-analysis                 default (keeps prod's meta consistent
                                         with the promoted main DB); skipped
                                         with a warning if dev has no meta DB.
    --local / --ssh                    Force local (on /hive host) vs SSH (from
                                         a laptop). Default: auto-detect.
    --min-data-tables INT              Refuse to promote if dev's main DB has
                                         fewer than N data_tables rows
                                         (default 1).
    --dry-run                          Preview without writing.

  rsync-dataset DATASETS...          Push the gitignored data payloads of
                                       the named dataset(s) up to a server
                                       instance (the push-direction mirror
                                       of sync-data). Copies ONLY gitignored
                                       files (config.yaml/preprocess.py
                                       arrive via git pull), creates the
                                       remote dir if missing, and preserves
                                       group-write. At least one name is
                                       required (no implicit "all").
    --instance dev|int|prod            Target instance. Default: dev.
    --host TEXT                        SSH host to write /hive (default
                                         hgwdev; 'psygene' proxy-jumps).
    --dry-run                          Preview without writing.

  e2e-deployed INSTANCE              Run playwright e2e tests locally
                                       against a deployed instance
                                       (dev | int | prod). Sets
                                       E2E_BASE_URL and delegates to
                                       scripts/test.sh e2e. No ssh / no
                                       rebuild. Useful for spot-checking a
                                       site without re-deploying.

  load-gene-descriptions             Build gene_descriptions.db from NCBI data
```
