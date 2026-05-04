# Gene-name cleanup: notes for wranglers

> **Audience:** SSPsyGene data wranglers (William, team). This is a living document — items will be added/removed as the cleanup work proceeds.
>
> **Status:** the architecture rewrite has landed (commit `15edd3d`, ticket [#121](https://github.com/sspsygene-dracc/psypheno/issues/121)). All datasets that used the old `ignore_missing` / `replace` / `to_upper` knobs have been migrated. The OO preprocessing library + tracked-action provenance are also now in ([#149](https://github.com/sspsygene-dracc/psypheno/issues/149), [#150](https://github.com/sspsygene-dracc/psypheno/issues/150)) — `preprocess.py` is now a `Pipeline` of tracked steps that emit a sibling `preprocessing.yaml`. This doc lists what's changed for you, what's still owed, and what to keep an eye on.

---

## 1. What changed at a glance

The per-mapping `gene_mappings:` block in each dataset's `config.yaml` got a new vocabulary:

| Old knob | New home | Notes |
|---|---|---|
| `ignore_missing:` | split into `non_resolving.drop_values:` (orphan, no stub) and `non_resolving.record_values:` (`manually_added=1` stub, no warn) | The old form silently orphaned rows AND skipped the central_gene insert — that's now explicit. |
| `replace:` (str → str) | `clean_gene_column(manual_aliases=...)` in your `preprocess.py`, OR a plain pandas op | Removed from the YAML schema. |
| `to_upper:` | `df[col] = df[col].str.upper()` in your `preprocess.py` | Removed from the YAML schema. |

The retired keys **hard-error** in load-db now — if you (or a colleague) puts `ignore_missing:` into a YAML, the build fails fast with a message pointing at the new home.

`multi_gene_separator:` and `ignore_empty:` are unchanged.

`preprocess.py` itself also changed: instead of free-function calls to `clean_gene_column(...)` plus loose `df.dropna(...)` / `df.drop_columns(...)` ops, you now build a **`Pipeline`** of tracked **`Step`s** that each record what they did into a `Tracker`. At the end of `main()` the tracker writes a sibling `preprocessing.yaml` so downstream users (and future-you) can audit exactly which manual cleanup was applied. See §2 for the cheat sheet, §3.5 for the provenance file.

---

## 2. The new YAML cheat sheet

```yaml
gene_mappings:
  - column_name: target_gene
    species: human
    link_table_name: gene
    perturbed_or_target: target
    ignore_empty: true                 # unchanged

    non_resolving:
      # 1. Literal values that should be ORPHANED (no central_gene stub, no warn).
      #    Use for placeholders, controls, paper-specific junk.
      drop_values: [not_available, none identified, GFP, NonTarget1]

      # 2. Pattern categories that should be ORPHANED.
      #    Useful when raw ENSG/clone IDs sneak in but you don't want
      #    them in the gene browser at all.
      drop_patterns: [rna_family]      # see §6 for the full list

      # 3. Literal values that should get a manually_added=1 stub
      #    in central_gene (no warn). Use for retired HGNC symbols
      #    with no clear successor.
      record_values: [SGK494, GATD3B, IQCD, CRIPAK]

      # 4. Pattern categories that should get a stub.
      #    Common case: ENSG IDs / GENCODE clones / contigs that
      #    aren't HGNC symbols but DO represent specific loci.
      record_patterns: [contig, gencode_clone, genbank_accession]
```

**Default behavior with no `non_resolving:` block:** unresolved values trigger a warning AND get a stub. Previously the loader silently swallowed warnings for values that looked like ENSG IDs / GENCODE clones / contigs / GenBank accessions; that implicit silencing is gone. To suppress those warnings without losing the rows, opt in explicitly via `record_patterns:` per dataset (see §4.5).

### `manual_aliases` (in preprocess.py)

For retired symbols where you know the canonical successor, pass them to `clean_gene` inside the pipeline:

```python
from pathlib import Path
from processing.preprocessing import (
    GeneSymbolNormalizer, MANUAL_ALIASES_HUMAN, Pipeline, Tracker,
)

DIR = Path(__file__).resolve().parent

def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    (
        Pipeline("cleaned.csv", tracker=tracker, normalizer=normalizer)
        .read_csv(DIR / "raw.csv")
        .clean_gene(
            "target_gene",
            species="human",
            excel_demangle=True,
            strip_make_unique=True,
            manual_aliases=MANUAL_ALIASES_HUMAN,   # the cross-dataset superset
        )
        .write_csv(DIR / "cleaned.csv")
        .run()
    )
    tracker.write(DIR / "preprocessing.yaml")
```

`MANUAL_ALIASES_HUMAN` is exported from `processing.preprocessing` and contains the 5-symbol human cross-dataset superset (`NOV→CCN3, MUM1→PWWP3A, QARS→QARS1, SARS→SARS1, TAZ→TAFAZZIN`). For per-dataset additions, merge a dict on top: `manual_aliases={**MANUAL_ALIASES_HUMAN, "FOO": "BAR"}`.

**Important:** the rescue target (`CCN3`, etc.) must resolve through the normalizer to a current approved HGNC symbol. If it doesn't, the call **raises `ValueError`** — guard against typos. So you cannot use `manual_aliases` for "fix a typo to a value that itself isn't a real symbol" (e.g. `ABALON. → ABALON` won't work because `ABALON` is itself retired). For those, use `.transform_column(col, func, description=...)` upstream of `clean_gene` — it's tracked so the YAML records the description.

---

## 3. Things to look at when running your next preprocess.py / load-db

### 3.1 The `<col>_raw` and `_<col>_resolution` columns

`clean_gene` writes the original (pre-cleaner) value into `<col>_raw` and the per-row tag into `_<col>_resolution`. **Both are kept by default in the cleaned output** — wranglers and end-users can audit each row from the cleaned TSV alone, no need to cross-reference the source.

```
target_gene  target_gene_raw   _target_gene_resolution
BRCA1        BRCA1             passed_through
SEPTIN9      9-Sep             rescued_excel
MATR3        MATR3.1           rescued_make_unique
CCN3         NOV               rescued_manual_alias
```

> **Migration note (#150):** the old free-function flow had every `preprocess.py` call `df.drop(columns=["_<col>_resolution"])` immediately after `clean_gene_column(...)`. The new pipeline form does NOT do that — keep both `<col>_raw` AND `_<col>_resolution` in the output. If you really need to drop the resolution column for an existing dataset's contract, use `.drop_columns(["_<col>_resolution"])` in the pipeline — that's tracked too, so the YAML records the drop.
>
> If you rename `<col>` later in the script, rename `<col>_raw` in lockstep (e.g. hsc-asd-organoid-m5 renames `hgnc_symbol → target_gene` and also `hgnc_symbol_raw → target_gene_raw`). The pipeline's `.rename({...})` step handles this — pass both names in the mapping dict.

### 3.2 Watch the load-db warning counts

After a rebuild, the two relevant log greps are:

```bash
grep -c "not in gene maps"                         /tmp/load.log   # genuine unknowns
grep -c "looks like a non-symbol identifier"       /tmp/load.log   # ENSG / clone / contig / GenBank that aren't yet whitelisted via record_patterns
```

Last full rebuild (2026-04-30) had:
- **75** genuine unknowns (down from ~6,651 in the [#126](https://github.com/sspsygene-dracc/psypheno/issues/126) baseline)
- **16,465** non-symbol-identifier values that aren't yet whitelisted via `record_patterns:` per dataset (this is the active to-do — see §4)

If you see either count climb, something regressed. Most likely cause: a new dataset import without `record_patterns:` set up, or an upstream HGNC source change.

### 3.3 Watch for `ValueError: manual_aliases: target ...`

If you add a new entry to `manual_aliases` and the target isn't a current HGNC symbol, preprocess.py crashes on first run. This is intentional (catches typos), but you'll see it as a hard fail rather than silent corruption. Picking a successor for a retired symbol? Verify with:

```bash
grep -P "^.+?\t<successor>\t" data/homology/hgnc_complete_set.txt
```

(The 2nd column is `symbol`, the approved HGNC symbol set.)

### 3.4 Watch row counts on `central_gene` and per-dataset tables

Each dataset migration can shift row counts:

- `record_values:` / `record_patterns:` entries → +N stubs in `central_gene` per unique value seen.
- `drop_values:` / `drop_patterns:` → row stays in dataset table, but no central_gene link → invisible to gene search.
- `manual_aliases:` (e.g. NOV → CCN3) → row stays, links to the existing CCN3 row → no stub created.

Spot-check after a rebuild:

```sql
-- Did manual_aliases route correctly?
SELECT row_id, human_symbol, hgnc_id, manually_added
FROM central_gene
WHERE human_symbol IN ('CCN3','QARS1','PWWP3A','TAFAZZIN','SARS1');
-- Expect: real HGNC entries, manually_added=0

-- NOV should NOT have its own row (it resolves to CCN3 now)
SELECT * FROM central_gene WHERE human_symbol = 'NOV';
-- Expect: 0 rows
```

### 3.5 The new sibling `preprocessing.yaml`

Every dataset that ships a `Pipeline`-based `preprocess.py` also writes a sibling `preprocessing.yaml` capturing every action: read, gene-clean, dropna, filter_rows, transform_column, rename, drop_columns, write. **Tracked in git**, so PR diffs of `preprocessing.yaml` make manual cleanup changes review-visible.

Shape (abbreviated):

```yaml
generated: '2026-05-04T10:49:25Z'
inputs:
- deg.txt
tables:
  deg_cleaned.txt:
  - step: read_csv
    source: deg.txt
    rows: 1627
    columns: [Gene, logFC, ...]
  - step: clean_gene_column
    column: Gene
    species: mouse
    flags: {excel_demangle: true}
    counts: {passed_through: 1622, rescued_excel: 3, unresolved: 2}
    dropped_rows: 0
    sample_unresolved: [Gm16091, Gm42864]
  - step: write_csv
    destination: deg_cleaned.txt
    rows: 1627
```

`load-db` slices this down to the per-table actions and stores them as JSON on `data_tables.preprocessing`. The web app surfaces a "Preprocessing (YAML)" download button next to the existing "Metadata (YAML)" button on `/download`.

Use this when:
- A user asks "why is row N missing the gene I expected?" — find the `_<col>_resolution` tag in the cleaned TSV, cross-reference with `counts` and `sample_unresolved` in the YAML.
- A reviewer wants to know what manual cleanup you did — point them at the diff of `preprocessing.yaml` rather than re-eyeballing the script.
- You're adding a new rescue helper (e.g. a new pattern category) — the rescue-tier counts in the YAML let you measure impact across all datasets at once.

**You don't need to write this file by hand.** As long as your `preprocess.py` calls `tracker.write(DIR / "preprocessing.yaml")` at the end of `main()`, it's regenerated every run.

---

## 4. Open decisions still owed by wranglers

These are parked in the YAML / preprocess.py awaiting your input. Each one is currently in a "safe but maybe wrong" bucket — the dataset still loads, but the call may not be biologically right.

### 4.1 Retired-with-known-successor symbols flagged for review

Currently in `record_values:` (creates a stub) but probably should move to `manual_aliases:` (resolves to a real successor) per dataset:

| Symbol | Possible successor(s) | Datasets where it appears |
|---|---|---|
| `MPP6` | `MPHOSPH6` (alias) or `PALS2` (prev_symbol) | brain_organoid_atlas, hsc-asd-organoid-m5, polygenic-risk-20, psychscreen |
| `LOR` | (ambiguous) | brain_organoid_atlas, hsc-asd-organoid-m5, psychscreen |
| `DEC1` | `BHLHE40` or `DELEC1` | hsc-asd-organoid-m5 |
| `C18orf21` | `RMP24` or `RMP24P1` | brain_organoid_atlas, dynamic_convergence, hsc-asd-organoid-m5, polygenic-risk-20, psychscreen |

**Action:** confirm the successor per paper context. For NDD / neuropsychiatric datasets, lean toward whichever protein the paper's discussion actually means. Once decided, move the entry from `record_values:` (in YAML) to `manual_aliases:` (in preprocess.py).

### 4.2 polygenic-risk-20 retired-symbol long tail

After the rna_family / extended-clone-regex helpers landed, polygenic-risk-20 Supp_1 still has 51 unique unresolved values. Sample:

`HDGFRP3`, `HDGFRP2`, `FLJ27365`, `DKFZP434E1119`, `OCLM`, `SGK110`, `SGK494`, `AGPAT9`, `SMC5-AS1`, `CRIPAK`, `C20ORF135`, `GGTA1P`, `C11orf48`, `MGC20647`, `PDPK2`, `SF3B14`, `STRA13`, `CXXC11`, `C6ORF165`, `CSRP2BP`, `C6orf123`, `EIF2S3L`, `TMEM155`, `SGK196`, `IQCD`, `B3GNT1`, `IQCA1`, `ZHX1-C8ORF76`, `LOC440461`, `DBC1`, `FLJ45079`, `MGC10955`, `5S_rRNA`, `CPEB3_ribozyme`, `C17orf61-PLSCR3`, `MPP6`, `DKK 1.00`, `DKK 2.00`, `DKK 3.00`, `DKK 4.00`, `ZAR 1.00`, …

Many have known successors:

- `AGPAT9` → `GPAT3`
- `SF3B14` → `SF3B6`
- `C11orf48` → `LBHD1`
- `STRA13` → `BHLHE40` or `CENPX` (depends on paper context)
- `B3GNT1` → `B4GAT1`
- `DBC1` → `BRINP1` or `CCAR2` (ambiguous)

**Action:** triage with the paper's discussion / supp methods open. Each goes either to `manual_aliases:` (successor known) or stays in `record_values:` (truly retired). The 5 `DKK 1.00` / `ZAR 1.00` values look like a NEW Excel mangling pattern (`DKK1` → `"DKK 1.00"`). If you confirm, we can extend the existing `excel_demangle` helper to handle that shape.

### 4.3 sfari `Slc30a3` species mismatch

In `SFARI-Gene_animal-rescues_07-08-2025release_10-03-2025export.csv`, the `model-symbol` column is configured as `species: human` — but `Slc30a3` is a mouse symbol. Looks like the animal-rescues file mixes model organisms per row and the YAML's blanket `species: human` isn't right for all of them.

**Action:** check the file. Likely fixes:
1. Upper-case `model-symbol` in a sfari `preprocess.py` (currently no preprocess.py for sfari) — the human normalizer has a case-insensitive mouse-fallback, so `SLC30A3` would resolve.
2. OR change the `species:` to per-row driven by another column.
3. OR the simplest: `record_values: [Slc30a3]` and call it a day if there's only the one offender.

### 4.4 hsc-asd-organoid-m5 silent dropna in supp 3

`hsc-asd-organoid-m5/preprocess.py:104-105` silently drops rows where `hgnc_symbol` is NaN/empty (~87,435 rows per supp 3 read). Per the §3.2 design intent, those rows should pass through and let `non_resolving:` decide their fate.

**Action:** when convenient — remove the dropna + empty-string filter. Add `ignore_empty: true` to the `target_gene` mapping in `config.yaml` so empty values orphan cleanly. **Beware:** this brings 87k extra rows into the DB. Real downstream impact (DB size, search results, dataset table view); do its own commit + rebuild check, not lumped with cleanup.

### 4.5 Policy: `record_patterns:` vs `drop_patterns:` for the new categories

When you do the per-dataset rollout of `non_resolving:` (currently 6 datasets need it — see the warning sweep in §3.2), you have to pick a bucket per category. The trade-off is what the web UI does for those values after the rebuild.

| Category | Recommendation | Reasoning |
|---|---|---|
| `contig` | `record_patterns:` | Each contig accession represents a specific locus that just lacks an HGNC symbol. A stub is correct; orphaning would lose the row from gene search even though it's a real measured thing. |
| `gencode_clone` (incl. all the new prefixes: `ABC7-`, `EM:`, `yR`, `XX-DJ`, `XX-FW`, `CITF`, `GHc-`, `SC22CB-`, `bP-`) | `record_patterns:` | Same as contig — clones map to specific loci. |
| `genbank_accession` | `record_patterns:` | Same — the accession identifies a specific deposited sequence. |
| `ensembl_human` / `ensembl_mouse` | `record_patterns:` for now | Same. Once #119's preprocess-time ENSG → symbol resolution lands, these can become `drop_patterns:` (or just go away). |
| `rna_family` | **`drop_patterns:`** | Different reasoning. RNA family labels (`Y_RNA`, `SNOR*`, `MIR*`, `U6`, `Vault`, `7SK`, `Metazoa_SRP`) are FAMILY annotations, not specific loci. The genome contains 100s–1000s of distinct paralogs sharing the label; `record_patterns` would create a single `manually_added=1` stub that conflates all of them. Searching `Y_RNA` in the web app would return ~2,000+ rows from polygenic-risk-20 alone, all behaving as if they're one gene. Misleading. With `drop_patterns:`, the rows stay in the dataset table view (the data is intact) but they're invisible to gene-search / cross-dataset cards — which is the right behavior for a family label. |

**TL;DR:**

```yaml
non_resolving:
  drop_patterns:   [rna_family]
  record_patterns: [contig, gencode_clone, genbank_accession]
  # for mouse-Ensembl-ID columns, also add `ensembl_mouse` to record_patterns
```

If you disagree on the `rna_family` call (e.g. for some specific paper, you actively want `Y_RNA` to be a navigable entity), use `record_patterns: [rna_family]` instead — the schema doesn't care.

---

## 5. Things to watch out for when adding a NEW dataset

If you're spinning up a new wrangle, the workflow is the same as before *except*:

1. **Build a `Pipeline`, not free-function calls.** `from processing.preprocessing import Pipeline, Tracker, GeneSymbolNormalizer` — see `data/datasets/mouse-perturb-4tf/preprocess.py` for the simplest template, or `hsc-asd-organoid-m5/preprocess.py` for a multi-sheet Excel one. The chainable builder methods (`read_csv`, `clean_gene`, `dropna`, `filter_rows`, `transform_column`, `rename`, `drop_columns`, `write_csv`) cover everything; `pipeline.add(MyCustomStep(...))` is the escape hatch.
2. **Call `tracker.write(DIR / "preprocessing.yaml")` at the end of `main()`.** Every step records into the tracker; this line persists it. The file is git-tracked so PR diffs surface every cleanup decision.
3. **Don't use `ignore_missing` / `replace` / `to_upper`** — they're gone. Use `non_resolving:` and `manual_aliases` instead.
4. **Check `<col>_raw` doesn't already exist** in your input frame. The cleaner raises `KeyError` if it does. If you have a column literally named `target_gene_raw` already, rename it before calling `clean_gene`.
5. **Don't drop rows outside the pipeline.** If you `dropna` or filter, do it via `.dropna(...)` / `.filter_rows(predicate, description=...)` — that way the YAML records the action and the row counts before/after.
6. **Decide your `record_patterns:` upfront.** If the dataset has raw ENSG IDs / contigs / GENCODE clones (which most large RNA-seq tables do), add `record_patterns: [contig, gencode_clone, genbank_accession]` to that mapping. Otherwise you'll spam the load-db log with non-symbol-identifier warnings.
7. **For mouse datasets:** if your gene column has Ensembl mouse IDs, opt in via `record_patterns: [ensembl_mouse]`.
8. **For datasets with raw RNA family labels** (Y_RNA, U6, SNORD42, MIR123, etc.): use `drop_patterns: [rna_family]`. These are family labels, not loci — orphan them rather than create a misleading single-stub central_gene entry.

---

## 6. Quick reference

### Dispatch order at load-db (per row, per gene_mapping)

1. `ignore_empty: true` AND value is empty/NaN → orphan, no warn.
2. `multi_gene_separator:` → split into multiple values.
3. Resolve in `central_gene` (after preprocess-time cleaning) → join.
4. **NEW**: value matches `drop_values:` or `drop_patterns:` → orphan, no stub, no warn.
5. **NEW**: value matches `record_values:` or `record_patterns:` → stub + link, no warn.
6. **DEFAULT**: warn + create stub + link.

### Pattern categories (for `drop_patterns:` / `record_patterns:`)

| Name | Matches | Examples |
|---|---|---|
| `ensembl_human` | `^ENSG\d+(?:\.\d+)?$` | `ENSG00000123456`, `ENSG00000123456.5` |
| `ensembl_mouse` | `^ENSMUSG\d+(?:\.\d+)?$` | `ENSMUSG00000071265` |
| `contig` | various Sanger/WGS-style contig accessions | `AC012345.6`, `AUXG01000058.1` |
| `gencode_clone` | BAC/PAC/cosmid/etc clone names | `RP11-783K16.5`, `CTD-2331H12.4`, `XX-DJ76P10__A.2` |
| `genbank_accession` | `^[A-Z]{1,2}\d{5,6}(\.\d+)?$` | `KC877982`, `L29074.1` |
| `rna_family` | RNA family LABELS (not loci) | `Y_RNA`, `U6`, `SNORA74`, `MIR5096`, `Metazoa_SRP`, `Vault`, `7SK` |

### Resolution tags in `_<col>_resolution`

| Tag | Meaning |
|---|---|
| `passed_through` | Resolved via the normalizer (or empty/NaN). |
| `rescued_excel` | Excel-mangled name (`9-Sep` → `SEPTIN9`). |
| `rescued_make_unique` | R `make.unique` `.N` suffix stripped. |
| `rescued_symbol_ensg` | `<symbol>_ENSG…` composite split. |
| `rescued_hgnc_id` | `HGNC:NNNNN` literal resolved. |
| `rescued_manual_alias` | Wrangler-supplied successor map hit. |
| `non_symbol_<category>` | Matched a `NON_SYMBOL_CATEGORIES` predicate. |
| `unresolved` | Genuinely unknown; falls into the load-db `non_resolving.fallback` path. |

### Verification recipe

```bash
sspsygene load-db 2>&1 | tee /tmp/load.log
```

Look out for "not in gene maps" or "looks like a non-symbol identifier"

---

## 7. Reference

- Library + Pipeline API:
  [`processing/src/processing/preprocessing/`](../processing/src/processing/preprocessing/)
  ([README](../processing/src/processing/preprocessing/README.md))
- Schema:
  [`processing/src/processing/types/gene_mapping.py`](../processing/src/processing/types/gene_mapping.py)
- Reference migrations:
  - Simplest pipeline:
    [`data/datasets/mouse-perturb-4tf/preprocess.py`](../data/datasets/mouse-perturb-4tf/preprocess.py)
  - Multi-sheet Excel + concat:
    [`data/datasets/hsc-asd-organoid-m5/preprocess.py`](../data/datasets/hsc-asd-organoid-m5/preprocess.py)
  - Free-function era (pre-#149): commit `15edd3d`, dataset `dynamic_convergence`
- Tickets: [#149](https://github.com/sspsygene-dracc/psypheno/issues/149) (OO library),
  [#150](https://github.com/sspsygene-dracc/psypheno/issues/150) (provenance tracking)
