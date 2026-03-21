# How to Add a Dataset to SSPsyGene

This guide walks you through every step of adding a new dataset to the SSPsyGene
website. Follow it carefully from top to bottom.

**What happens when you add a dataset:** You download data from a paper, convert
it to a clean CSV or TSV file, write a YAML configuration file that describes it,
and then load it into the database. The website then automatically shows the data
on gene pages.

---

## Table of Contents

1. [Get the data](#step-1-get-the-data)
2. [Create a dataset directory](#step-2-create-a-dataset-directory)
3. [Preprocess the data](#step-3-preprocess-the-data-to-csvtsv)
4. [Write config.yaml](#step-4-write-configyaml)
5. [Test locally](#step-5-test-locally)
6. [Commit to git](#step-6-commit-to-git)
7. [Deploy](#step-7-deploy)
8. [Troubleshooting](#troubleshooting)

---

## Step 1: Get the data

Find the supplemental data for the paper you want to add. This is usually:

- A supplementary Excel spreadsheet attached to the paper
- A CSV/TSV download from a database or web portal
- Data files hosted on a data repository (GEO, Zenodo, etc.)

**Important things to write down** (you will need these later):

- The URL where you downloaded the data
- The paper's DOI (e.g. `10.1038/s41586-025-10047-5`)
- The paper's PubMed ID (PMID), if it has one
- Which supplementary table or figure the data comes from
- The full author list, journal name, and publication year

**Do NOT commit the raw downloaded files to git.** Raw data files (especially
Excel spreadsheets) are large and do not belong in the repository. Only your
preprocessing script and the final processed CSV/TSV should be in the repo
(and even the CSV/TSV may be gitignored if it's large — more on this later).

---

## Step 2: Create a dataset directory

All datasets live in `data/datasets/`. Create a new directory for your dataset:

```bash
mkdir data/datasets/my-new-dataset
```

**Naming rules:**
- Use lowercase letters, numbers, and hyphens only
- Make it short but descriptive
- Examples: `psychscreen`, `mouse-perturb-4tf`, `brain-organoid-atlas`

---

## Step 3: Preprocess the data to CSV/TSV

Your goal is to produce one or more clean **CSV** or **TSV** files that the
loading pipeline can read. Each file will become one "table" on the website.

### What the final file must look like

- **First row** must be column headers
- **One row per data point** (typically one row per gene, or one row per
  gene + condition combination)
- Must have at least one column containing **gene symbols** (e.g. `SHANK3`,
  `Foxg1`, `dlg2`). This is how the website links data to gene pages.
- Numeric columns (p-values, fold changes, etc.) should contain numbers, not
  text like "N/A" — use empty cells for missing values

### Write a preprocessing script

If the raw data is not already in clean CSV/TSV format (and it usually isn't),
write a Python script to convert it. Save this script in your dataset directory.

**Example:** See `data/datasets/geschwind_2026_cnv/preprocess.py` for a real
example that reads 45 sheets from an Excel file and outputs a single TSV.

A simple preprocessing script looks like this:

```python
"""
Preprocess My Dataset.

Reads the supplementary Excel file and produces a clean TSV.

Usage:
    python preprocess.py

Input:  ~/Downloads/SupplementaryTable.xlsx (sheet "DEG Results")
Output: data/datasets/my-new-dataset/results.tsv
"""

import pandas as pd
from pathlib import Path

# Point this to wherever you downloaded the raw file
INPUT_PATH = Path.home() / "Downloads" / "SupplementaryTable.xlsx"
OUTPUT_PATH = Path(__file__).parent / "results.tsv"

def main():
    df = pd.read_excel(INPUT_PATH, sheet_name="DEG Results", engine="openpyxl")

    # Drop rows where the gene symbol is missing
    df = df.dropna(subset=["gene_symbol"])

    # Keep only the columns we need
    df = df[["gene_symbol", "log2FoldChange", "pvalue", "padj", "cell_type"]]

    df.to_csv(OUTPUT_PATH, sep="\t", index=False)
    print(f"Wrote {len(df)} rows to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
```

**Key points:**
- The input path points to your Downloads folder (or wherever you saved the
  raw file). This raw file is NOT committed to git.
- The output path is inside your dataset directory. This processed file IS
  what the website loads.
- Document where the input data came from in the script's docstring.

Run your script to generate the output file:

```bash
cd data/datasets/my-new-dataset
python preprocess.py
```

Check that the output looks reasonable:

```bash
head -5 results.tsv
wc -l results.tsv
```

---

## Step 4: Write config.yaml

This is the most important step. The `config.yaml` file tells the loading
pipeline everything it needs to know about your dataset. Create the file at:

```
data/datasets/my-new-dataset/config.yaml
```

### Complete annotated example

Below is a fully annotated example. Read every comment carefully.

```yaml
# ============================================================================
# Publication information
# ============================================================================
publication:
  authors:                          # Full author list, one per line
    - Last, First M.
    - Last, First M.
    - Last, First M.
  year: 2026                       # Publication year (integer)
  journal: "Nature Neuroscience"    # Journal name
  doi: "10.1038/s41593-025-12345-6" # DOI (without https://doi.org/ prefix)
  pmid: "12345678"                  # PubMed ID as a string, or null if not yet indexed

# ============================================================================
# Who loaded this dataset and when
# ============================================================================
maintainers:
  - name: Your Name                 # Your full name
    email: you@ucsc.edu             # Your email
    date: "2026-03-21"              # Today's date in YYYY-MM-DD format
    comment: Initial table creation  # Short note

# ============================================================================
# Tables — this is where the actual data is defined
# One dataset can have multiple tables (e.g. different experiments from
# the same paper). Each table becomes a separate entry on the website.
# ============================================================================
tables:
  - table: my_dataset_degs          # Internal table name. Must be unique across
                                    # ALL datasets. Use lowercase, underscores only.
                                    # Convention: datasetname_description

    # --- Labels (how this table appears on the website) ---

    shortLabel: my_dataset_degs     # URL-safe identifier. Lowercase letters,
                                    # numbers, and underscores ONLY (a-z, 0-9, _).
                                    # No spaces, no hyphens, no uppercase.

    mediumLabel: "My Dataset DEGs"  # Short display name (shown in table headers)

    longLabel: "Differentially expressed genes from My Dataset (Smith et al. 2026)"
                                    # Longer descriptive title

    description: >                  # Full description (can be multiple lines
      Differentially expressed genes from RNA-seq analysis of iPSC-derived      # using > for folded text)
      cortical neurons. Includes log2 fold changes and FDR-adjusted p-values
      across multiple cell types.

    # --- Data source ---

    source: "Supplementary Table 2"  # Where you got the data (for your own records)

    in_path: results.tsv            # Path to the data file, RELATIVE to your
                                    # dataset directory. This is the file you
                                    # created in Step 3.

    separator: "\t"                 # Use "\t" for TSV files, "," for CSV files.
                                    # IMPORTANT: must be in quotes!

    # --- Metadata tags ---

    organism: "Homo sapiens (iPSC-derived neurons)"  # Species and sample type

    assay: expression               # What type of assay produced this data.
                                    # Must be one of these exact values:
                                    #   expression    — Gene Expression (RNA-seq)
                                    #   spatial       — Spatial Transcriptomics
                                    #   behavior      — Behavioral Assays
                                    #   perturbation  — Perturbation Screen
                                    #   curated       — Curated Database
                                    #   phenotype     — Phenotype Annotation
                                    #
                                    # You can also use a list for multiple types:
                                    #   assay: [spatial, perturbation]

    disease:                        # Which diseases this data relates to.
      - asd                         # Must be from this list:
      - ndd                         #   asd     — Autism Spectrum Disorder
                                    #   scz     — Schizophrenia
                                    #   bipolar — Bipolar Disorder
                                    #   ndd     — Neurodevelopmental Disorders
                                    # Use [] for an empty list if not disease-specific.

    categories:                     # Free-text tags describing the data.
      - bulk RNA-seq                # These are for browsing/filtering on the website.
      - iPSC-derived neurons        # Use whatever makes sense.
      - cortical development

    links:                          # URLs to the paper or data source
      - https://doi.org/10.1038/s41593-025-12345-6

    # --- Statistical columns ---

    pvalue_column: pvalue           # Which column contains the p-value.
                                    # Use the column name EXACTLY as it appears
                                    # in your CSV/TSV header.
                                    # Can also be a list: [pvalue, pval_interaction]

    fdr_column: padj                # Which column contains the FDR-adjusted p-value.
                                    # Same rules as pvalue_column.

    # --- Gene mappings (CRITICAL — read carefully) ---

    gene_mappings:                  # This tells the pipeline which column(s)
                                    # contain gene names and how to link them
                                    # to the central gene database.

      - column_name: gene_symbol    # The column name in your CSV/TSV that
                                    # contains gene symbols.

        link_table_name: gene       # Name for the link table that connects
                                    # your data to the gene database. Usually
                                    # just "gene". If you have multiple gene
                                    # columns, give each a different name
                                    # (e.g. "target_gene", "perturbed_gene").

        species: human              # What species the gene symbols are from.
                                    # Must be one of:
                                    #   human     — Human gene symbols (HGNC)
                                    #   mouse     — Mouse gene symbols (MGI)
                                    #   zebrafish — Zebrafish gene symbols (ZFIN)

        is_perturbed: false         # Is this the gene that was experimentally
                                    # perturbed (knocked out, overexpressed, etc.)?
                                    # For most datasets, this is false.

        is_target: false            # Is this the gene whose expression was
                                    # measured as a result?
                                    # For most non-perturbation datasets: false.
                                    #
                                    # IMPORTANT RULE: If you set is_perturbed: true
                                    # on any gene mapping, you MUST also have
                                    # exactly one mapping with is_target: true
                                    # (and vice versa). If your dataset is NOT a
                                    # perturbation experiment, set BOTH to false.

    # --- Column splitting (usually not needed) ---

    split_column_map: []            # Leave as empty list [] unless you need to
                                    # split a column. See "Advanced" section below.

    # --- Custom field labels (optional) ---

    fieldLabels:                    # Override how column names are displayed on
      cell_type: "Brain cell type"  # the website. The KEY is the column name
                                    # (lowercased, non-alphanumeric chars replaced
                                    # with underscores). The VALUE is the display label.
                                    #
                                    # Common columns already have default labels
                                    # (pvalue, padj, logfc, etc.) — you only need
                                    # to add labels for columns specific to your data.

    # --- Changelog (optional but recommended) ---

    changelog:
      - date: "2026-03-21"
        message: "Initial data load"
```

### Minimal example (simplest possible config)

If your dataset is a simple human expression dataset with one table, here is
the minimum you need:

```yaml
publication:
  authors:
    - Smith, John
    - Doe, Jane
  year: 2026
  journal: "Nature"
  doi: "10.1038/..."
  pmid: null

maintainers:
  - name: Your Name
    email: you@ucsc.edu
    date: "2026-03-21"
    comment: Initial table creation

tables:
  - table: smith_2026_degs
    shortLabel: smith_2026_degs
    mediumLabel: "Smith 2026 DEGs"
    longLabel: "Differentially expressed genes (Smith et al. 2026)"
    description: "DEGs from RNA-seq of postmortem brain tissue."
    source: "Supplementary Table 1"
    assay: expression
    disease: ["asd"]
    categories:
      - bulk RNA-seq
    organism: "Homo sapiens"
    in_path: results.csv
    separator: ","
    split_column_map: []
    pvalue_column: pvalue
    fdr_column: padj
    gene_mappings:
      - column_name: gene
        link_table_name: gene
        species: human
        is_perturbed: false
        is_target: false
```

### Multiple tables from one paper

If a paper has multiple experiments (e.g. different assays, different species),
you add multiple entries under `tables:`:

```yaml
tables:
  - table: smith_2026_human_degs
    shortLabel: smith_2026_human
    # ... all other fields ...
    in_path: human_results.csv

  - table: smith_2026_mouse_degs
    shortLabel: smith_2026_mouse
    # ... all other fields ...
    in_path: mouse_results.csv
```

Each table can have its own data file, gene mappings, assay type, etc.

### Perturbation datasets

If your dataset is from a perturbation experiment (CRISPR screen, knockdown,
overexpression, etc.), you need **two gene mapping entries** — one for the
gene that was perturbed and one for the gene whose expression was measured:

```yaml
    gene_mappings:
      - column_name: target_gene      # The measured gene
        link_table_name: Target_Gene
        species: human
        is_perturbed: false
        is_target: true               # <-- this is the measured gene

      - column_name: perturbed_gene   # The knocked-out/overexpressed gene
        link_table_name: Perturbed_Gene
        species: human
        is_perturbed: true            # <-- this is the perturbed gene
        is_target: false
```

### Mouse or zebrafish data

If your gene symbols are from mouse or zebrafish, change the `species` field:

```yaml
    gene_mappings:
      - column_name: gene_symbol
        link_table_name: gene
        species: mouse        # or: zebrafish
        is_perturbed: false
        is_target: false
```

The pipeline will automatically map mouse/zebrafish genes to their human
orthologs so they appear on the correct gene pages.

If your mouse gene symbols are lowercase (e.g. `shank3` instead of `Shank3`),
add `to_upper: true` to convert them:

```yaml
        to_upper: true
```

### Advanced gene mapping options

These are optional fields you can add to a gene mapping if needed:

```yaml
    gene_mappings:
      - column_name: gene_symbol
        link_table_name: gene
        species: human
        is_perturbed: false
        is_target: false

        # Skip specific values that aren't real gene names:
        ignore_missing: ["NA", "None", "Intergenic"]

        # Skip empty/NaN values silently (instead of warning):
        ignore_empty: true

        # If a column contains multiple genes separated by a delimiter:
        multi_gene_separator: ","
        # Example: a cell containing "SHANK3,NRXN1" will be split into two links

        # Fix gene names that don't match the database:
        replace:
          "TBCE.1": "TBCE"
          "MATR3.1": "MATR3"

        # For Ensembl mouse gene IDs instead of symbols:
        gene_type: "ensmus"
```

### Column splitting (split_column_map)

This is rarely needed. Use it when a column contains two pieces of information
joined by a separator that you want to split apart. For example, if a column
called `perturbation` contains values like `Foxg1_0` (gene name + replicate
index):

```yaml
    split_column_map:
      - source_col: perturbation
        new_col1: _perturbation_gene
        new_col2: _perturbation_idx
        sep: "_"
```

This keeps the original column and adds two new columns.

### Common mistakes

1. **Wrong `shortLabel` format:** Must be lowercase letters, numbers, and
   underscores only. No hyphens, no spaces, no uppercase. `my-dataset` is
   wrong; `my_dataset` is correct.

2. **Wrong `separator` value:** Must be `","` or `"\t"` — in quotes. Just a
   bare comma or tab character will not work.

3. **Mismatched `column_name`:** The `column_name` in gene_mappings must
   exactly match a column header in your CSV/TSV file (case-insensitive, but
   special characters are replaced with underscores internally).

4. **Missing `is_perturbed`/`is_target` pair:** If you set one to `true`, you
   must set the other on a different gene mapping. You cannot have `is_target: true`
   without a corresponding `is_perturbed: true` somewhere.

5. **Duplicate `table` names:** The `table` field must be unique across ALL
   datasets in the entire project, not just within your config file.

6. **Forgetting `split_column_map: []`:** Even if you don't use column
   splitting, you must include `split_column_map: []` (empty list).

---

## Step 5: Test locally

Testing is a multi-step process. Start with the fastest test and work up.

### 5a. Load just your dataset (fast — ~1 minute)

This loads only your dataset into a fresh database, skipping everything else.
It's the fastest way to check if your config.yaml is correct:

```bash
sspsygene load-db --dataset my-new-dataset
```

If this fails, read the error message carefully. Common errors:

- `FileNotFoundError` — your `in_path` is wrong or the file doesn't exist
- `KeyError` — a `column_name` in gene_mappings doesn't match any column in
  your data file
- `ValueError` about short_label — your `shortLabel` contains invalid characters

Fix the error and try again.

### 5b. Load the full database without slow steps (~5 minutes)

Once your single dataset loads, try loading ALL datasets together. Use these
flags to skip the slow parts (index creation and meta-analysis):

```bash
sspsygene load-db --no-index --skip-meta-analysis
```

This checks that your dataset doesn't conflict with any other dataset (e.g.
duplicate table names). If this works, move on.

### 5c. Load the full database (slow — ~15-30 minutes)

This is the production-ready load with all indexes and meta-analysis:

```bash
sspsygene load-db
```

This takes a while because it computes combined p-values across all datasets.
You only need to do this once you're confident everything is correct.

### 5d. Check the website

Start the development web server:

```bash
cd web
npm run dev
```

Then open `http://localhost:3000` in your browser and:

1. Search for a gene that should be in your dataset
2. Check that your dataset appears on the gene's page
3. Verify that the data looks correct (column labels, values, etc.)
4. Check the "All Datasets" page to see your dataset listed

---

## Step 6: Commit to git

### What to commit

- `data/datasets/my-new-dataset/config.yaml` — always commit this
- `data/datasets/my-new-dataset/preprocess.py` — always commit this
- Small reference files needed by the preprocessing script (e.g. JSON gene
  lists, mapping files)

### What NOT to commit

- Raw downloaded data files (Excel spreadsheets, original downloads)
- Large processed data files (CSV/TSV) — these are generated by your
  preprocessing script and can be recreated
- Database files (`.db`, `-wal`, `-shm`) — these are generated by `load-db`

### Update .gitignore

If your data files are large, add them to a `.gitignore` file in your dataset
directory:

```bash
# data/datasets/my-new-dataset/.gitignore
results.tsv
*.xlsx
```

### Git commands

If you're not familiar with git, here are the commands:

```bash
# 1. Check what files have changed
git status

# 2. Add the files you want to commit (list each file explicitly)
git add data/datasets/my-new-dataset/config.yaml
git add data/datasets/my-new-dataset/preprocess.py
git add data/datasets/my-new-dataset/.gitignore

# 3. Do NOT add data files! If you see large CSV/TSV/Excel files in
#    "git status", make sure they're in .gitignore.

# 4. Commit with a descriptive message
git commit -m "Add my-new-dataset: DEGs from Smith et al. 2026"

# 5. Push to GitHub
git push
```

---

## Step 7: Deploy

Deployment is a two-stage process. Always deploy to **internal** first to
verify, then to **production**.

There are three server instances (see `docs/server-architecture.md` for full
details):

| Instance | URL | Purpose |
|----------|-----|---------|
| **Internal (int)** | https://psypheno-int.gi.ucsc.edu | Staging / pre-publication data |
| **Production (prod)** | https://psypheno.gi.ucsc.edu | Public-facing site |
| **Dev** | https://psypheno-dev.gi.ucsc.edu | Mirror of production (auto-updated with prod) |

Prod and dev share the same code and data — deploying to prod automatically
updates dev too.

### Prerequisites

- SSH access to `hgwdev` or `psygene` (the deployment scripts run directly
  on the server, not from your laptop)
- `sudo` access on `psygene` (needed to restart services)

### 7a. Deploy to internal

SSH into the server and run the deploy script from the repository root:

```bash
ssh hgwdev      # or: ssh psygene
cd /hive/groups/SSPsyGene/sspsygene_website_int

# Deploy with database reload:
./deploy-int.sh --load-db
```

This will:
1. `git pull` the latest code
2. Rebuild the database (this takes a while)
3. Run `npm run build` to rebuild the web app
4. Restart the `sspsygene-int` systemd service

After it finishes, verify your dataset at https://psypheno-int.gi.ucsc.edu.

### 7b. Deploy to production

Once you've verified everything looks correct on the internal site:

```bash
cd /hive/groups/SSPsyGene/sspsygene_website

# Deploy with database reload:
./deploy-prod.sh --load-db
```

This restarts both the `sspsygene` (prod) and `sspsygene-dev` (dev) services,
since they share the same code and data.

After it finishes, verify at https://psypheno.gi.ucsc.edu/.

### Deploy without reloading the database

If you only changed code (not data), you can deploy without `--load-db`:

```bash
./deploy-int.sh       # code-only deploy to internal
./deploy-prod.sh      # code-only deploy to production
```

---

## Troubleshooting

### "FileNotFoundError: [Errno 2] No such file or directory"

Your `in_path` in config.yaml doesn't match the actual filename. Check:
- Is the file in the right directory?
- Is the filename spelled correctly (case-sensitive)?
- Did you run your preprocessing script to generate it?

### "KeyError: 'gene_symbol'"

A `column_name` in your gene_mappings doesn't match any column in your data
file. Open your CSV/TSV and check the exact column header names. Remember that
the match is case-insensitive, but special characters are replaced with
underscores internally.

### "ValueError: shortLabel ... contains invalid characters"

Your `shortLabel` has characters other than lowercase letters, numbers, or
underscores. Fix it — no hyphens, no spaces, no uppercase.

### "Duplicate table name"

Another dataset already uses the same `table` name. Use a more specific name
that includes your dataset name as a prefix.

### Gene symbols not linking to gene pages

- Check that `species` is correct (human/mouse/zebrafish)
- Check that the gene symbols in your data match standard nomenclature
  (HGNC for human, MGI for mouse, ZFIN for zebrafish)
- If symbols are non-standard, use the `replace` option in gene_mappings
- If symbols are lowercase mouse genes, add `to_upper: true`

### "Permission denied" during deployment

You need SSH access to the UCSC servers (hgwdev and psygene). Contact the
system administrator if you don't have access.

### The website doesn't show my dataset after deployment

1. Did you include `--load-db` in the deploy command? Without it, only code
   is deployed — the database is not rebuilt.
2. Check the deployment output for errors during the `load-db` step.
3. Try searching for a specific gene that you know is in your dataset.

---

## Quick Reference

| What | Command |
|------|---------|
| Load single dataset (fast test) | `sspsygene load-db --dataset NAME` |
| Load all datasets, skip slow steps | `sspsygene load-db --no-index --skip-meta-analysis` |
| Load all datasets (production) | `sspsygene load-db` |
| Start dev server | `cd web && npm run dev` |
| Deploy to internal (on server) | `cd /hive/groups/SSPsyGene/sspsygene_website_int && ./deploy-int.sh --load-db` |
| Deploy to production (on server) | `cd /hive/groups/SSPsyGene/sspsygene_website && ./deploy-prod.sh --load-db` |

---

## Real Examples

Look at these existing datasets for reference:

- **Simple human expression dataset:** `data/datasets/psychscreen/config.yaml`
- **Perturbation dataset (two gene columns):** `data/datasets/polygenic-risk-20/config.yaml`
- **Mouse dataset:** `data/datasets/mouse-perturb-4tf/config.yaml`
- **Dataset with preprocessing script:** `data/datasets/geschwind_2026_cnv/` (see `preprocess.py` and `config.yaml`)
- **Zebrafish dataset:** `data/datasets/zebraAsd/config.yaml`
- **Multi-gene separator:** `data/datasets/geschwind_2026_cnv/config.yaml` (uses `multi_gene_separator`)
