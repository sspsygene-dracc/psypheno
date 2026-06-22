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
5. [Test on the server](#step-5-test-on-the-server)
6. [Commit to git](#step-6-commit-to-git)
7. [Deploy](#step-7-deploy)
8. [Promoting a dataset from internal to production](#promoting-a-dataset-from-internal-to-production)
9. [Troubleshooting](#troubleshooting)

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

**Do NOT commit raw downloaded files or processed data files to git.** Data
files (especially Excel spreadsheets and large CSVs/TSVs) are large and do not
belong in the repository. Only your preprocessing script and config files should
be committed — the processed files are regenerated on the server by running
your preprocessing script (see Step 6 for details).

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

**Example:** See `data/datasets/mouse-perturb-4tf/preprocess.py` for the
simplest real example, or `data/datasets/hsc-autism-organoid-m5/preprocess.py`
for a multi-sheet Excel case.

Use the **`processing.preprocessing` library** to build a `Pipeline` of
tracked steps. Every step records what it did, and `Pipeline.run()`
auto-emits a per-output sidecar `<output>.preprocessing.yaml` next to
the cleaned data file (#158) so downstream users can audit exactly
which manual changes were applied.

```python
"""
Preprocess My Dataset.

Reads the supplementary Excel file and produces a clean TSV plus a
sidecar results.tsv.preprocessing.yaml provenance log.

Usage:
    python preprocess.py
"""

from pathlib import Path

from processing.preprocessing import (
    GeneSymbolNormalizer,
    Pipeline,
    Tracker,
)

DIR = Path(__file__).resolve().parent


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline("results.tsv", tracker=tracker, normalizer=normalizer)
        .read_csv(DIR / "raw.csv")
        .dropna(["gene_symbol"])
        .clean_gene(
            "gene_symbol",
            species="human",
            excel_demangle=True,       # 1-Mar -> MARCHF1
            strip_make_unique=True,    # MATR3.1 -> MATR3
        )
        .write_tsv(DIR / "results.tsv")
        .run()
    )
    # Sidecar results.tsv.preprocessing.yaml has been written next to the
    # cleaned TSV — no explicit tracker.write() call is needed.


if __name__ == "__main__":
    main()
```

**Available pipeline steps** (all chainable, all tracked):
- `read_csv` / `read_tsv` / `from_dataframe` — start the pipeline
- `clean_gene(column, species=..., **rescue_flags)` — gene-name resolution
  (Excel demangle, R make.unique strip, ENSG→symbol via `ensembl_mapper`,
  HGNC ID resolution, manual aliases)
- `dropna(columns)` / `filter_rows(predicate, description=...)` — drops
- `rename(mapping)` / `reorder(columns)` / `drop_columns(columns)` —
  schema reshape
- `transform_column(column, func, description=...)` — one-off custom edits
- `insert_column(name, value, position=None)` — constants or computed cols
- `split_column(source, new_col1, new_col2, sep)` — split a compound
  identifier like `Foxg1_3` into gene + index (keeps the source column)
- `write_csv(path)` / `write_tsv(path)` — finish

For unchanged companion files (e.g. a patient list referenced from another
table), use the free `copy_file(src, dst, tracker=tracker)` helper — it
records a `copy_file` action without loading a DataFrame.

The cross-dataset alias superset `MANUAL_ALIASES_HUMAN` is also exported
from `processing.preprocessing`; merge per-dataset additions on top if
needed.

**Key points:**
- The input path points to wherever you saved the raw file. Raw files are
  typically NOT committed to git.
- The cleaned output is committed (or pointed at by `in_path` in
  `config.yaml`).
- One `<output>.preprocessing.yaml` sidecar is written per output file
  (next to the cleaned data). **It is gitignored — do not commit it.** Its
  `generated:` timestamp changes every run, so committed copies just churn the
  diff. It is regenerated by `preprocess.py` (and `sspsygene preprocess` /
  deploy `--preprocess`); load-db reads it when present and stores nothing when
  absent. For multi-sheet patterns that
  pd.concat several sub-pipelines into one combined output, call
  `tracker.write_concat(out_path, inputs=[...], **summary)` once after
  the manual `to_csv` to record the concat and emit the sidecar.
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
  sspsygene_grants:                 # SSPsyGene consortium grants acknowledged in the
    - "RM1MH132648"                 #   paper. Empty list `[]` = checked, not consortium-funded.
                                    # Drives the "SSPsyGene-funded" / "Grant number"
                                    # facets on /publications. Look up the paper's
                                    # funding section against this table:
                                    #   UCLA    RM1MH132651
                                    #   Rutgers R01MH131296
                                    #   Yale    RM1MH132648
                                    #   Broad   R01MH128366
                                    #   UCSC    U24MH132628
                                    #   Scripps R01HG012819
                                    #   WUSTL   RM1MH138313

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

    mediumLabel: "Smith 2026 - bulk RNA-seq DEGs in iPSC Cortical Neurons"
                                    # Short display name (shown in table
                                    # headers and dataset cards). MUST follow
                                    # the standardized format:
                                    #   "First Author Year - Assay Medium"
                                    # See "Dataset title format" below for the
                                    # full rule.

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

    organism: "Homo sapiens (iPSC-derived neurons)"  # Free-form description shown in dataset cards.

    organism_key: human             # Controlled-vocab tag used by the
                                    # /most-significant breakdown radio buttons.
                                    # Must be one of these exact values:
                                    #   human       — Human
                                    #   mouse       — Mouse
                                    #   zebrafish   — Zebrafish
                                    #
                                    # You can use a list if a table genuinely
                                    # mixes organisms (e.g. cross-species
                                    # comparison): organism_key: [human, mouse]
                                    # Omit entirely (or use []) for tables that
                                    # don't fit a single organism — they will
                                    # be excluded from the per-organism
                                    # meta-analysis.
                                    #
                                    # New organism keys are added in
                                    # data/datasets/globals.yaml under
                                    # organismTypes.

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

    condition:                      # Which conditions this data relates to.
      - autism                      # Must be from this list:
      - ndc                         #   autism  — Autism
                                    #   scz     — Schizophrenia
                                    #   bipolar — Bipolar Disorder
                                    #   ndc     — Neurodevelopmental Conditions
                                    # Use [] for an empty list if not condition-specific.

    categories:                     # Free-text tags describing the data.
      - bulk RNA-seq                # These are for browsing/filtering on the website.
      - iPSC-derived neurons        # Use whatever makes sense.
      - cortical development

    links:                          # Supplementary URLs (data downloads, code,
                                    # protocols, GEO accessions, etc.). The
                                    # paper DOI lives in `publication.doi`
                                    # — don't repeat it here.
                                    #
                                    # Each entry is a dict with `url`, an
                                    # optional `label` (becomes the displayed
                                    # link text), and an optional `description`
                                    # (rendered as a hover tooltip).
      - url: https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345
        label: GEO — GSE12345
        description: Raw and processed RNA-seq counts (optional)
      - url: https://github.com/example/analysis-code
        label: GitHub — analysis code
                                    # Bare URL strings are still accepted as a
                                    # back-compat shortcut; they render with
                                    # the hostname as link text.

    # --- Statistical columns ---

    pvalue_column: pvalue           # Which column contains the p-value.
                                    # Use the column name EXACTLY as it appears
                                    # in your CSV/TSV header.
                                    # Can also be a list: [pvalue, pval_interaction]
                                    #
                                    # OPTIONAL — omit this line entirely if your
                                    # data does not have a p-value column.

    fdr_column: padj                # Which column contains the FDR-adjusted p-value.
                                    # Same rules as pvalue_column.
                                    # Also optional — omit if not applicable.

    effect_column: logFC            # Which column contains the signed effect
                                    # size (logFC, log2FC, beta, limma_coef,
                                    # etc.). When set, the gene-search page
                                    # renders a histogram + volcano plot for
                                    # this table at load-db time, with the
                                    # queried gene marked.
                                    #
                                    # OPTIONAL — omit if your table has no
                                    # signed effect-size column. Single value
                                    # only (no list).

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

        perturbed_or_target: target # Required. Either "perturbed" or "target".
                                    #   target    — the gene whose expression
                                    #               or activity was measured as
                                    #               a readout (most observational
                                    #               datasets, all DEG tables).
                                    #   perturbed — the gene that was
                                    #               experimentally manipulated
                                    #               (CRISPRi/CRISPRa, RNAi,
                                    #               knockout, mutant line) or
                                    #               flagged as the upstream
                                    #               cause (e.g. patient-mutation
                                    #               catalogs, SFARI risk genes).
                                    #
                                    # A perturbation experiment with both a
                                    # perturbed gene column and a measured-readout
                                    # column needs two gene_mappings — one with
                                    # perturbed_or_target: perturbed, one with
                                    # perturbed_or_target: target. Tables can
                                    # also have just one direction (pure-target
                                    # or pure-perturbed).

    # --- Custom field labels / column descriptions (optional) ---
    #
    # fieldLabels lets you add human-readable descriptions to columns.
    # On the website, these appear as tooltip icons (ⓘ) next to column
    # headers — hover over the icon to see the description.
    #
    # Use this to explain what non-obvious columns mean, what units
    # they are in, or any other context a reader would need.
    #
    # KEY:   the column name, lowercased, with non-alphanumeric chars
    #        replaced by underscores (e.g. "Log2(FC)" → "log2_fc_")
    # VALUE: the description text shown in the tooltip
    #
    # Common columns already have global default labels defined in
    # data/datasets/globals.yaml (pvalue, padj, fdr, logfc, basemean,
    # cell_type, etc.). You only need to add fieldLabels for columns
    # that are specific to your dataset or where the global default
    # isn't descriptive enough. Per-table labels override the globals.

    fieldLabels:
      cell_type: "Brain cell type"
      hc_at_birth_sd_: "Head circumference at birth (standard deviations)"
      lr: "Likelihood ratio test statistic"

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
    mediumLabel: "Smith 2026 - bulk RNA-seq DEGs in Postmortem Brain"
    longLabel: "Differentially expressed genes (Smith et al. 2026)"
    description: "DEGs from RNA-seq of postmortem brain tissue."
    source: "Supplementary Table 1"
    assay: expression
    condition: ["autism"]
    categories:
      - bulk RNA-seq
    organism: "Homo sapiens"
    organism_key: human
    in_path: results.csv
    separator: ","
    pvalue_column: pvalue            # omit if no p-value column
    fdr_column: padj                 # omit if no FDR column
    effect_column: logFC             # omit if no signed effect-size column
    gene_mappings:
      - column_name: gene
        link_table_name: gene
        species: human
        perturbed_or_target: target
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
        perturbed_or_target: target

      - column_name: perturbed_gene   # The knocked-out/overexpressed gene
        link_table_name: Perturbed_Gene
        species: human
        perturbed_or_target: perturbed
```

### Mouse or zebrafish data

If your gene symbols are from mouse or zebrafish, change the `species` field:

```yaml
    gene_mappings:
      - column_name: gene_symbol
        link_table_name: gene
        species: mouse        # or: zebrafish
        perturbed_or_target: target
```

The pipeline will automatically map mouse/zebrafish genes to their human
orthologs so they appear on the correct gene pages.

Mouse symbols are matched case-insensitively, so lowercase input
(e.g. `shank3`) resolves to the approved symbol (`Shank3`) automatically —
you don't need to do anything special for casing.

### Advanced gene mapping options

These are optional fields you can add to a gene mapping if needed:

```yaml
    gene_mappings:
      - column_name: gene_symbol
        link_table_name: gene
        species: human
        perturbed_or_target: target

        # Skip empty/NaN values silently (instead of warning):
        ignore_empty: true

        # If a column contains multiple genes separated by a delimiter:
        multi_gene_separator: ","
        # Example: a cell containing "SHANK3,NRXN1" will be split into two links
```

**Gene-name cleanup belongs in `preprocess.py`, not `config.yaml`.** The old
`to_upper`, `replace`, `ignore_missing`, and `gene_type` knobs have been
removed from `config.yaml` (using them now fails `load-db`). Do these in your
preprocessing script (Step 3) instead:

- **Fix names that don't match the database** (the old `replace:`) → pass
  `clean_gene(column, species=..., manual_aliases={"OLD": "NEW"})`. For
  `R make.unique`-style `.1`/`.2` suffixes (`MATR3.1` → `MATR3`), the
  default `strip_make_unique=True` already handles it.
- **Skip values that aren't real gene names** (the old `ignore_missing:`) →
  drop the rows with `.filter_rows(...)` / `.dropna(...)` in preprocess.py,
  or — for control labels and predicted-gene stubs you want to *keep* — use
  the `non_resolving:` block (`control_values` / `record_values`).
- **Ensembl IDs instead of symbols** (the old `gene_type:`) → handled
  automatically; `clean_gene(..., resolve_via_ensembl_map=True)` (the
  default) converts `ENSG…` / `ENSMUSG…` to symbols and preserves the
  original in `<col>_raw`.

See [docs/wrangler_gene_cleanup.md](wrangler_gene_cleanup.md) for the full
gene-cleanup migration guide.

### Column splitting

This is rarely needed. Use it when a column contains two pieces of information
joined by a separator that you want to split apart. Do this in your
`preprocess.py` (see Step 3) with the `split_column` pipeline step — **not** in
`config.yaml`. For example, if a column called `perturbation` contains values
like `Foxg1_0` (gene name + replicate index):

```python
    .split_column(
        source="perturbation",
        new_col1="_perturbation_gene",
        new_col2="_perturbation_idx",
        sep="_",
    )
```

This keeps the original column and adds two new columns. See
`data/datasets/mouse-perturb-4tf/preprocess.py` for a real example.

### Dataset title format

Every table's `mediumLabel` MUST follow the consortium-wide format:

```
First Author Last Name Year - Assay Medium
```

Example: `"Deans 2026 - arrayed CRISPRa/shRNA ECCITE-seq in iGLUT Neurons"`.

The pieces:

- **First Author Last Name** — the surname of the **first author of the
  dataset's actual publication** (the paper listed in `publication.authors`).
  Use this even when the data is redistributed by a portal or aggregator
  paper with a different author — the portal/source can be acknowledged in
  parentheses at the end of the title (e.g. `"… (via PsychSCREEN)"`) or in
  the `source:` field. Compound surnames are kept whole — write
  `"Fernandez Garcia 2026"`, not `"Garcia 2026"`.
- **Year** — the publication year as a 4-digit number.
- **` - `** — a space-dash-space, not a colon (per the 4/21/2026 wrangler
  meeting).
- **Assay** — the technique that produced the data
  (e.g. `bulk RNA-seq`, `Perturb-seq`, `CRISPRi screen`, `Perturb-FISH`,
  `snRNA-seq Pseudobulk DEGs`, `Curated Annotations`).
- **Medium** — what biological system the assay was applied to
  (e.g. `iPSC Cortical Neurons`, `Mouse Cortex`, `iPSC-derived Astrocytes`,
  `Postmortem Brain`, `Zebrafish`).

Datasets with multiple tables from one paper share the author/year prefix and
differentiate by the Assay/Medium half — see e.g. `data/datasets/zebra-autism/`
(`Mendes 2023 - in vivo Functional Screen …` vs
`Mendes 2023 - Sleep-Wake and Visual-Startle Behavior …`).

### Common mistakes

1. **Wrong `shortLabel` format:** Must be lowercase letters, numbers, and
   underscores only. No hyphens, no spaces, no uppercase. `my-dataset` is
   wrong; `my_dataset` is correct.

2. **Wrong `separator` value:** Must be `","` or `"\t"` — in quotes. Just a
   bare comma or tab character will not work.

3. **Mismatched `column_name`:** The `column_name` in gene_mappings must
   exactly match a column header in your CSV/TSV file (case-insensitive, but
   special characters are replaced with underscores internally).

4. **Wrong `perturbed_or_target` value:** Must be exactly `perturbed` or
   `target` (lowercase, no quotes needed). Each gene_mapping must include this
   field — there is no default and no neutral value.

5. **Duplicate `table` names:** The `table` field must be unique across ALL
   datasets in the entire project, not just within your config file.

---

## Step 5: Test on the server

Testing is done on the server (psygene). You'll use the **internal
(int)** instance to test — that's what it's for.

### One-time setup: install conda and the `sspsygene` CLI

If you haven't set up conda on psygene yet, you need to do this once. Install
Miniconda by following the official instructions:
https://docs.conda.io/en/latest/miniconda.html

Then create the `sspsygene` environment and install the processing pipeline:

```bash
# Create a new conda environment with Python 3.12
# (3.12, not 3.13: our pinned pandas==2.2.1 has no prebuilt wheel for 3.13,
# so 3.13 forces a fragile source build — see pre-meeting-setup.md.)
conda create -n sspsygene python=3.12
conda activate sspsygene

# Install the sspsygene CLI tool (from the repo's processing directory)
cd /hive/groups/SSPsyGene/sspsygene_website_int/processing
pip install -e .
```

The `pip install -e .` command installs the `sspsygene` command-line tool in
"editable" mode, meaning it always uses the current code in the repo. You only
need to run this once (or again if dependencies change in `pyproject.toml`).

### Set up your environment (every session)

Each time you SSH in, you need to activate conda and set environment variables:

```bash
ssh psygene
cd /hive/groups/SSPsyGene/sspsygene_website_int

# Activate conda
source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh
conda activate sspsygene

# Set environment variables (these point to the int instance)
export SSPSYGENE_CONFIG_JSON="$(pwd)/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="$(pwd)/data"
export SSPSYGENE_DATA_DB="$(pwd)/data/db/sspsygene.db"
```

### 5a. Load just your dataset (fast — ~1 minute)

This builds a temporary database containing **only your dataset**. It's the
fastest way to check if your config.yaml is correct:

```bash
sspsygene load-db --dataset my-new-dataset
```

**Note:** This creates a fresh database with only your dataset in it. The
website will only show that one dataset. This is fine for testing — you'll
rebuild the full database in the next step.

If this fails, read the error message carefully. Common errors:

- `FileNotFoundError` — your `in_path` is wrong or the file doesn't exist
- `KeyError` — a `column_name` in gene_mappings doesn't match any column in
  your data file
- `ValueError` about short_label — your `shortLabel` contains invalid characters

Fix the error and try again until this step passes.

### 5b. Load the full database without slow steps

Once your single dataset loads, try loading ALL datasets together. Use these
flags to skip the slow parts (index creation and meta-analysis):

```bash
sspsygene load-db --no-index --skip-meta-analysis
```

This checks that your dataset doesn't conflict with any other dataset (e.g.
duplicate table names). If this works, move on.

### 5c. Load the full database (slow)

This is the production-ready load with all indexes and meta-analysis:

```bash
sspsygene load-db
```

This takes a while because it computes combined p-values across all datasets.
You only need to do this once you're confident everything is correct.

### 5d. Check the website on the development site

Open https://psypheno-dev.gi.ucsc.edu in your browser — the web process
auto-detects the rebuilt database (inode/mtime check in `web/lib/db.ts`)
and picks up the new data on the next request, so no service restart is
needed. Then:

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

- Raw downloaded data files (Excel spreadsheets, original downloads from the
  internet). Add these to `.gitignore`.
- Database files (`.db`, `-wal`, `-shm`) — these are already globally
  gitignored.

### What about the processed CSV/TSV files?

**You should generally NOT commit the processed CSV/TSV files.** Data files can
be large and bloat the git repository. Since all server instances run on `/hive`
(which is backed up), the processed files are safe on the filesystem without
being in git.

Instead, run your preprocessing script on the server after `git pull` to
regenerate the processed files. Make sure the raw data is accessible from the
server (e.g. via a download URL in your preprocessing script).

The exception is if your processed files are very small (under ~1 MB). In that
case it's fine to commit them for convenience.

### Update .gitignore

Add a `.gitignore` in your dataset directory to exclude raw downloads and
processed data files:

```bash
# data/datasets/my-new-dataset/.gitignore

# Raw downloads
*.xlsx
*.xls
raw_download.csv

# Processed data files (regenerated by preprocess.py)
results.tsv
results.csv
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

# 3. Do NOT add data files (CSV/TSV/Excel)! These should be in .gitignore.
#    Only commit config.yaml, preprocess.py, and small reference files.

# 4. Commit with a descriptive message
git commit -m "Add my-new-dataset: DEGs from Smith et al. 2026"

# 5. Push to GitHub
git push
```

---

## Step 7: Deploy

For wranglers, "deploying" is just **rebuilding the database** on the right
server instance. The three instances (dev, int, prod — see
`docs/server-architecture.md`) each have their own checkout and database on
`/hive`, and each running web process auto-detects when its SQLite file has
been swapped and reopens the connection on the next request — no service
restart, no sudo.

The three sites are independent deploys — **not** a staging chain:

- **Public datasets** → rebuild on **dev** first to verify, then on **prod**.
  (Dev is the staging instance for prod.)
- **Embargoed / pre-publication datasets** → rebuild on **int** only. int is a
  parallel site for embargoed data and never auto-promotes anywhere.
- A dataset can later move from int to prod if it becomes publishable; that's
  a deliberate operator action (see *Promoting an embargoed dataset to
  production* below), not part of any automatic flow.

There are two ways to do this:

### 7a. From your laptop with `sspsygene deploy` (recommended)

`sspsygene deploy` is a CLI that handles the whole deploy from your laptop:
it pushes your branch (if needed), SSHes to hgwdev, runs `git pull`, and
optionally runs `load-db` and/or restarts the web server. Most public-dataset
rollouts follow this pattern:

```bash
# 1. Deploy to dev and rebuild the dev DB:
sspsygene deploy --instances dev --load-db
```

Verify at https://psypheno-dev.gi.ucsc.edu. Once you're happy, push the same
to prod:

```bash
sspsygene deploy --instances prod --load-db   # then check psypheno (live)
```

For an **embargoed** dataset, skip dev and prod and deploy directly to int:

```bash
sspsygene deploy --instances int --load-db    # then check psypheno-int
```

You can also pass multiple instances at once (e.g. `--instances dev,prod`);
they're iterated in dev→int→prod order purely for log readability but are
independent deploys — failures on one don't roll back the others. Useful flags:

- `--preprocess` — also re-run each dataset's `preprocess.py` on the server
  before `load-db`. Use when a `preprocess.py` change has landed and the
  cleaned data files on the server are now stale.
- `--build` — run `npm install` + `npm run build` on the server, then
  restart the Next.js web service. **Wranglers don't need this** — it's
  only for JS / web code changes (and only Johannes typically runs it,
  since the restart step only works for the user who owns the systemd
  unit). If you genuinely need a web rebuild deployed, ping Johannes.
- `--restart` / `--no-restart` — explicit override of the restart step.
  Default tracks `--build`. Data-only updates don't need a restart
  because the web process auto-detects DB swaps.
- `--no-push` — skip the local `git push` (handy if you've already pushed).
- `--run-tests` — after each site's build, run `scripts/test.sh server` on
  psygene plus `scripts/test.sh e2e` against the deployed URL. Aborts on
  first failure.

Full reference: `sspsygene deploy --help` and `docs/development.md`.

> **Important:** if your dataset's processed data files (the cleaned
> `results.tsv`, raw downloads) are not yet on the target server's
> `/hive/groups/SSPsyGene/sspsygene_website*/data/datasets/<your-dataset>/`,
> the `load-db` will fail (or silently skip your dataset). Push them first with
> **`sspsygene rsync-dataset <name> --instance dev`** (see
> [7c](#7c-from-the-server-with-sspsygene-wrangler-deploy) below), or pass
> `--preprocess` so the server re-runs `preprocess.py` itself.

### 7b. Manual rebuild on the server (fallback)

If `sspsygene deploy` isn't available — or you want to do exactly one step
and nothing else — you can SSH in and rebuild by hand:

```bash
ssh psygene
cd /hive/groups/SSPsyGene/sspsygene_website_int   # or _dev, or prod path
git pull

# Activate the conda env and set env vars for this instance:
source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh
conda activate sspsygene
export SSPSYGENE_CONFIG_JSON="$(pwd)/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="$(pwd)/data"
export SSPSYGENE_DATA_DB="$(pwd)/data/db/sspsygene.db"

sspsygene load-db
```

After it finishes, verify at the corresponding URL:
- Internal: https://psypheno-int.gi.ucsc.edu
- Dev: https://psypheno-dev.gi.ucsc.edu
- Production: https://psypheno.gi.ucsc.edu

**Important:** Before rebuilding, make sure the processed data files exist on
the server (processed CSV/TSVs are not committed to git — see
[7c](#7c-from-the-server-with-sspsygene-wrangler-deploy) for how to push them).

### 7c. From the server with `sspsygene wrangler-deploy`

`sspsygene deploy` (7a) SSHes into psygene from your laptop and runs `git pull`
**non-interactively** — which means if the server checkout ever needs your git
credentials, the prompt is swallowed and the pull fails silently (or hangs).
The wrangler-side flow avoids that by splitting the deploy into a push from
your laptop and a build *on* the server, where you have a real shell and your
own credentials:

```bash
# 1. On your laptop — commit and push your config/preprocess changes:
git commit -am "Add dataset my-dataset"
git push

# 2. On your laptop — push the gitignored data payloads up to dev. This sends
#    ONLY the raw downloads + cleaned <table>.tsv files (never config.yaml /
#    preprocess.py, which arrive via git pull), group-writable so the next
#    wrangler can overwrite them:
sspsygene rsync-dataset my-dataset --instance dev

# 3. SSH to the server and run the build there:
ssh -J hgwdev psygene
sspsygene wrangler-deploy --instances dev --load-db
```

`wrangler-deploy` runs the same steps as `deploy` (git pull → preprocess →
load-db → build → restart → tests) but as **local** subprocesses on psygene
instead of over SSH, so `git pull` runs in the foreground and any password
prompt is visible and answerable. Its flags mirror `deploy`
(`--instances`, `--load-db`, `--preprocess`, `--build/--no-build`,
`--restart/--no-restart`, `--run-tests`) minus `--no-push` (there's no push
step — you pushed from your laptop in step 1). The e2e test suite is skipped
on the server (no playwright browsers there); run it from your laptop with
`sspsygene e2e-deployed <instance>`.

`rsync-dataset` takes one or more dataset names (there is no implicit "all"),
plus `--instance dev|int|prod` (default `dev`), `--host` (default `hgwdev`),
and `--dry-run`:

```bash
sspsygene rsync-dataset sfari psychscreen --instance int
sspsygene rsync-dataset my-dataset --instance dev --dry-run   # preview only
```

It warns if any `in_path` named in your `config.yaml` is absent both locally
and on the server, since `load-db` would fail on it.

> **Restart caveat (multi-user):** the `--restart` step (and `--build`, which
> implies it) kill-and-respawns the npm processes, but the systemd units run as
> `User=jbirgmei`, so `kill` only bounces a service when *Johannes* runs it.
> For other wranglers it no-ops with a warning — ask Johannes, or
> `sudo systemctl restart sspsygene{,-dev,-int}` if you have sudo. Data-only
> deploys (`--load-db` without `--build`) don't need a restart anyway: the web
> process auto-detects the swapped DB.

---

## Promoting a dataset from internal to production

Use this **only when an embargoed dataset on int becomes publishable** and
you want to make it part of prod. It is **not** part of any automatic flow —
int and prod are independent sites with possibly disjoint dataset sets, and
most embargoed datasets stay on int. Public datasets follow the dev → prod
path in Step 7 and don't go through int at all.

Each instance has its **own data directory** on `/hive`. The `config.yaml`
and preprocessing script live in git, so they reach prod automatically via
`git pull`. But **processed CSV/TSV files are not in git**, so they must be
copied between instances (or regenerated by re-running the preprocessing
script).

The cleanest path is to push the data files from your laptop with
`sspsygene rsync-dataset my-dataset --instance prod` (it copies only the
gitignored payloads, group-writable, without dirtying prod's git tree) and then
run `sspsygene wrangler-deploy --instances prod --load-db` on the server — the
[7c](#7c-from-the-server-with-sspsygene-wrangler-deploy) flow, pointed at prod.

If you're already SSHed into the server and want to copy directly between
instance trees on `/hive`, you can rsync int → prod by hand:

```bash
ssh psygene

# 1. Copy processed data files from int to prod (config.yaml is harmlessly
#    overwritten with the same content from git):
rsync -av \
  /hive/groups/SSPsyGene/sspsygene_website_int/data/datasets/my-dataset/ \
  /hive/groups/SSPsyGene/sspsygene_website/data/datasets/my-dataset/

# 2. Rebuild the production database (same steps as Step 7, but in the
#    prod directory):
cd /hive/groups/SSPsyGene/sspsygene_website
git pull
source $HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh
conda activate sspsygene
export SSPSYGENE_CONFIG_JSON="$(pwd)/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="$(pwd)/data"
export SSPSYGENE_DATA_DB="$(pwd)/data/db/sspsygene.db"
sspsygene load-db
```

Verify at https://psypheno.gi.ucsc.edu.

Alternative to rsync: re-run your preprocessing script in the prod dataset
directory if the raw input is accessible there.

### Important notes

- **Do not skip the data file copy.** Running `sspsygene load-db` without
  the data files will cause the load to fail or silently skip the dataset.
- Dev has its own directory (`sspsygene_website_dev`); if you want the
  dataset on dev too, repeat the rsync + `sspsygene load-db` there (with
  env vars pointing at the dev directory).

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
- If symbols are non-standard, fix them in `preprocess.py` with
  `clean_gene(..., manual_aliases={"OLD": "NEW"})` (see Step 3)
- Lowercase mouse symbols (`shank3`) resolve automatically — they're
  matched case-insensitively, so no extra step is needed

### "Permission denied" during deployment

You need SSH access to the UCSC servers (especially psygene). Contact the
system administrator if you don't have access.

### `git pull` fails with "Permission denied (publickey)" on psygene

The deploy's `git pull` runs **on psygene** and authenticates to GitHub
from there (the server checkouts use a `git@github.com:…` remote). If it
fails with `Permission denied (publickey)`, psygene has no GitHub-usable
key for you. The deploy forwards your laptop's SSH agent (`ssh -A`), so
usually loading your key locally (`ssh-add`) is enough — but if your
agent has no key or forwarding is disabled, generate a key that lives on
psygene and add it to your GitHub account. Both options are written up in
[docs/tutorial/pre-meeting-setup.md](tutorial/pre-meeting-setup.md) →
section 10c ("GitHub access for the deploy's `git pull`").

### The website doesn't show my dataset after deployment

1. Did `sspsygene load-db` actually finish without errors? Re-read its output.
2. Are the `SSPSYGENE_*` env vars pointing at the intended instance's
   directory? A common mistake is rebuilding the int database while the
   vars still point at prod (or vice versa).
3. Try searching for a specific gene that you know is in your dataset.
4. Give the web process a few seconds — it only re-opens the database on
   the next incoming request.

---

## Quick Reference

| What | Command |
|------|---------|
| Load single dataset (fast test) | `sspsygene load-db --dataset NAME` |
| Load all datasets, skip slow steps | `sspsygene load-db --no-index --skip-meta-analysis` |
| Load all datasets (full build) | `sspsygene load-db` |
| Deploy to dev (from laptop) | `sspsygene deploy --instances dev --load-db` |
| Deploy to internal (from laptop) | `sspsygene deploy --instances int --load-db` |
| Deploy to production (from laptop) | `sspsygene deploy --instances prod --load-db` |
| Push data files to a server (from laptop) | `sspsygene rsync-dataset NAME --instance dev` |
| Deploy from the server (after `ssh -J hgwdev psygene`) | `sspsygene wrangler-deploy --instances dev --load-db` |
| Manual deploy to internal (on server) | `cd /hive/groups/SSPsyGene/sspsygene_website_int && git pull && sspsygene load-db` |
| Manual deploy to dev (on server) | `cd /hive/groups/SSPsyGene/sspsygene_website_dev && git pull && sspsygene load-db` |
| Manual deploy to production (on server) | `cd /hive/groups/SSPsyGene/sspsygene_website && git pull && sspsygene load-db` |

---

## Real Examples

Look at these existing datasets for reference:

- **Simple human expression dataset:** `data/datasets/psychscreen/config.yaml`
- **Perturbation dataset (two gene columns):** `data/datasets/polygenic-risk-20/config.yaml`
- **Mouse dataset:** `data/datasets/mouse-perturb-4tf/config.yaml`
- **Dataset with preprocessing script:** `data/datasets/geschwind_2026_cnv/` (see `preprocess.py` and `config.yaml`)
- **Zebrafish dataset:** `data/datasets/zebra-autism/config.yaml`
- **Multi-gene separator:** `data/datasets/geschwind_2026_cnv/config.yaml` (uses `multi_gene_separator`)
