# SSPsyGene Data Website

A web platform for exploring neuropsychiatric genetics data from the
[SSPsyGene consortium](https://sspsygene.ucsc.edu/) at UCSC. Integrates differential
expression, perturbation screens, phenotype annotations, and curated databases
into a searchable gene-centric interface.

**Live site:** https://psypheno.gi.ucsc.edu/

## Repository Structure

```
data/
  datasets/     Per-dataset configs, data files, and preprocessing scripts
  homology/     Gene homology mapping files (HGNC, MGI, ZFIN, Alliance)
  db/           Generated SQLite database (not in git)
processing/     Python pipeline — loads datasets into SQLite (Click CLI)
web/            Next.js web application (React, TypeScript, better-sqlite3)
docs/           Documentation
```

## Documentation

| Document | Description |
|----------|-------------|
| [Adding Datasets](docs/adding-datasets.md) | Step-by-step guide for data wranglers adding new datasets |
| [Server Architecture](docs/server-architecture.md) | Production/dev/internal server instances and deployment |
| [Local Development](docs/development.md) | Setting up and running the project locally |

## Quick Start

```bash
# Install Python pipeline
conda create -n sspsygene python=3.13 && conda activate sspsygene
cd processing && pip install -e . && cd ..

# Set environment variables
export SSPSYGENE_DATA_DIR="$(pwd)/data"
export SSPSYGENE_CONFIG_JSON="processing/src/processing/config.json"
export SSPSYGENE_DATA_DB="$(pwd)/data/db/sspsygene.db"

# Build database and start web app
sspsygene load-db
cd web && npm install && npm run dev
```

See [docs/development.md](docs/development.md) for full setup instructions.
