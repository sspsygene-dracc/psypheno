# SSPSyGene Data Website

The SSPsyGene data website is a web platform for exploring neuropsychiatric genetics data from multiple experimental datasets and phenotypes. The project integrates differential expression data, perturbation studies, and mouse phenotype data from various sources into a unified SQLite database with a Next.js web interface.

## Project Structure

The repository is organized into three main directories:

- **`data/`** - Raw data files and generated SQLite database

  - `datasets/` - Experimental datasets (mouse perturbations, zebrafish, psychscreen, etc.)
  - `homology/` - Gene homology mapping files for cross-species analysis
  - `db/sspsygene.db` - Generated SQLite database (created by processing pipeline)

- **`processing/`** - Python data processing pipeline

  - Data loading and transformation scripts
  - Gene name mapping and homology resolution
  - Database schema creation and population
  - CLI tool: `sspsygene load_db`

- **`web/`** - Next.js web application
  - React components for data visualization
  - API routes for database queries
  - Gene search and dataset browsing interface

## Generating Data

Raw data files are organized by dataset in `data/datasets/`. Most datasets include a `BUILD` and/or a `README.txt` file with instructions for downloading and preparing the data. `README.txt` files generally contain human-readable pointers to papers and where the data is from, while BUILD files contain commands to download and/or process the data.

### Dataset Download and Preparation

Read the `README.txt` files and run the `BUILD` scripts in each dataset directory to download and prepare the required data files.

Each dataset directory also contains a `config.yaml` file that describes how its raw files should be turned into database tables.

### Dataset Configuration Files (`config.yaml`)

Every subdirectory under `data/datasets/` should contain a `config.yaml` with the following structure:

- **Top-level metadata**
  - **`publication`**: Information about the source study.
    - `authors`: List of author names (strings).
    - `year`: Publication year (integer).
    - `journal`: Journal or resource name (string).
    - `doi` / `pmid`: Optional identifiers (strings or `null`).
  - **`maintainers`**: One or more entries describing who set up or maintains this dataset configuration.
    - `name`: Maintainer name.
    - `email`: Contact email.
    - `date`: ISO date string (e.g. `"2025-11-28"`).
    - `comment`: Short free-text comment about the change (e.g. "Initial table creation").

- **`tables`**: List of table definitions to create from this dataset.
  Each entry has:
  - **`table`**: Unique table name in the SQLite database (e.g. `psychscreen_age_deg`, `mouse_perturb_deg`).
  - **`shortLabel`**: Short human-readable label shown in the web UI.
  - **`longLabel`**: Longer description of what the table represents.
  - **`description`**: Multi-line YAML string describing the dataset in more detail (free text).
  - **`links`**: List of relevant URLs (paper, resource page, data download, etc.).
  - **`categories`**: List of descriptive tags (e.g. `bulk RNA-seq`, `CRISPR screening`, `autism genetics`).
  - **`organism`**: Species or preparation (e.g. `"Homo sapiens (postmortem brain)"`, `"Mus musculus"`).
  - **`in_path`**: Relative path to the input data file within this dataset directory.
    - Example: `Age_DEGcombined.csv`, `MGI_PhenotypicAllele_annotated.rpt`.
  - **`split_column_map`**: Optional list of column-splitting rules.
    - Each rule:
      - `source_col`: Existing column name in the input file.
      - `new_col1`, `new_col2`: Names of new columns to create.
      - `sep`: String separator used to split the original column (e.g. `"_"`).
    - Use `[]` if no splitting is needed.
  - **`separator`**: Field separator for the input file:
    - `","` for CSV, `"\t"` for tab-delimited, etc.

  - **`gene_mappings`**: List of mappings telling the loader how to interpret gene identifiers in this table.
    Each entry may include:
    - `column_name`: Column in the input file that contains gene identifiers.
    - `link_table_name`: Logical name of the gene-related field in the database (e.g. `gene`, `perturbation_gene`, `guide_gene`).
    - `species`: Species context for these identifiers (e.g. `human`, `mouse`, `zebrafish`).
    - `gene_type` (optional): When non-symbol IDs are used, e.g. `ensmus` for Ensembl mouse IDs.
    - `to_upper` (optional): Boolean; if `true`, convert the column’s values to uppercase before mapping.
    - `ignore_missing` (optional): List of placeholder values to skip (e.g. `"NonTarget1"`, `"SafeTarget"`, `"not_available"`).
    - `ignore_empty` (optional): If `true`, empty strings are ignored.
    - `is_perturbed`: Boolean; `true` if this column describes the perturbed gene in an experiment.
    - `is_target`: Boolean; `true` if this column is the primary gene being analyzed/linked in the table.
    - `replace` (optional): Mapping from raw values to cleaned gene symbols (e.g. `"TBCE.1": "TBCE"`).
    - `comment` (optional): Free-text notes clarifying any quirks of the mapping.

The processing pipeline discovers datasets by scanning `data/datasets/*/config.yaml` (see `processing/src/processing/config.json`), so adding a new `config.yaml` in a new dataset directory is sufficient to register it with the loader.

### How to Add a New Dataset (for UCSC data wranglers)

To add a new dataset so it appears in the SSPSyGene web interface:

1. **Create a new dataset directory**
   - Under `data/datasets/`, make a new subdirectory with a descriptive name (e.g. `my_new_dataset/`).

2. **Place raw / processed input files**
   - Download or generate the tabular files to be loaded (CSV, TSV, or similar).
   - Place them directly in the new dataset directory.

3. **Create `config.yaml`**
   - Following the structure above, define:
     - Top-level `publication` and `maintainers`.
     - One or more table entries under `tables:` describing each logical table you want in the database.
     - For each table, specify `in_path`, `separator`, and `gene_mappings` so the loader can find and map genes correctly.
   - Use existing datasets (e.g. `brain_organoid_atlas`, `psychscreen`, `mouse-perturb-4tf`) as templates for similar types of data.

4. **Verify file paths and column names**
   - Check that:
     - `in_path` matches the actual filename (including extension) in the dataset directory.
     - Column names in `split_column_map` and `gene_mappings` match the headers in the input file exactly (case-sensitive).

5. **Reload the database**
   - Once the new dataset and its `config.yaml` are in place, re-run the database loading step (see **Loading the Database** below).

6. **Restart the web server (production only)**
   - After the database has been rebuilt on the production server, restart the systemd service so the web app sees the updated database:
     ```bash
     sudo /usr/bin/systemctl restart sspsygene-data
     ```

## Loading the Database

Once the raw data files and `config.yaml` files are in place, build and run the processing pipeline to create the SQLite database.

### 1. Install Python Dependencies

```bash
conda create -n sspsygene python=3.13.7
conda activate sspsygene 
cd processing
pip install -e .
```

### 2. Set Environment Variables

Set the data directory root (where `datasets/`, `homology/`, and `db/` live) and the processing config path:

```bash
# typically the repository's data directory during local development
export SSPSYGENE_DATA_DIR="$(pwd)/data"

# processing config JSON
export SSPSYGENE_CONFIG_JSON="processing/src/processing/config.json"
```

On the UCSC `hgwdev` server, the code and data currently live in:

```bash
/hive/groups/SSPsyGene/sspsygene_website
```

On that machine, you would normally set:

```bash
export SSPSYGENE_DATA_DIR="/hive/groups/SSPsyGene/sspsygene_website/data"
export SSPSYGENE_CONFIG_JSON="/hive/groups/SSPsyGene/sspsygene_website/processing/src/processing/config.json"
```

### 3. Load Database

```bash
sspsygene load_db
```

This will:

- Read gene homology mapping files
- Process each dataset defined in `config.json`
- Create gene mappings between species (mouse, human, zebrafish)
- Populate the SQLite database at `$SSPSYGENE_DATA_DIR/db/sspsygene.db`

The configuration file (`processing/src/processing/config.json`) defines where to write the database (`out_db`), which homology mapping files to use, and the root directory (`table_config_root`) where dataset `config.yaml` files are discovered.

### After Reloading the Database (Production)

After rebuilding the database on `hgwdev`, restart the SSPSyGene data web service so the running Next.js app sees the updated SQLite file:

```bash
sudo /usr/bin/systemctl restart sspsygene-data
```

The website currently runs on https://sspsygene-data.ucsc.edu.

## Starting the Web Server

The web application is a Next.js app that queries the SQLite database.

### 1. Install Dependencies

```bash
cd web
npm install
```

### 2. Set Environment Variable

Point to the SQLite database path (generated by the processing step):

```bash
export SSPSYGENE_DATA_DB="$SSPSYGENE_DATA_DIR/db/sspsygene.db"
```

### 3. Build for Production

```bash
npm run build
```

## Features

- **Gene search**: Search across datasets by gene symbol with fuzzy matching
- **Dataset browser**: View all loaded datasets with descriptions
- **Cross-species mapping**: Automatic homology resolution for mouse, human, and zebrafish genes
- **Phenotype data**: Integration of mouse phenotype data from JAX
- **Perturbation studies**: CRISPR perturbation results and differential expression data

## Development Notes

- The database uses `better-sqlite3` for Node.js and Python `sqlite3` for processing
- Gene names are mapped to Entrez IDs internally for consistency
- The web app runs in readonly mode for safety
- See `TODOs.txt` for planned additions and improvements
