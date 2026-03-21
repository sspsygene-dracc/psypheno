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

## CLI Reference

```
sspsygene load-db [OPTIONS]          Load/rebuild the database
  --dataset TEXT                     Load only this dataset
  --no-index                        Skip index creation
  --skip-meta-analysis              Skip combined p-value computation
  --skip-gene-descriptions          Skip gene description copying
  --skip-missing-datasets           Skip missing input files

sspsygene deploy [OPTIONS]           Deploy to servers
  --prod-only / --int-only           Target one environment
  --load-db                          Rebuild DB during deploy
  --no-push                          Skip git push
  --no-restart                       Skip service restart

sspsygene load-gene-descriptions     Build gene_descriptions.db from NCBI data
```
