# Redesign gene-name normalization architecture (sspsygene)

> **For a fresh agent:** this plan is fully self-contained. Read this top-to-bottom before exploring. The repo is `/Users/jbirgmei/prog/sspsygene` (code) and `sspsygene-dracc/psypheno` (issue tracker — separate GitHub repo, use `gh` against it). Project context is in [CLAUDE.md](CLAUDE.md).

## 1. Background

The `#126` tracker on `sspsygene-dracc/psypheno` is rolling out a "move gene-name cleanup out of `load-db` and into per-dataset preprocessing" architecture. Five per-dataset migrations landed in late April 2026:

| Ticket | Dataset | Commit | Helpers used |
|---|---|---|---|
| #146 (reference) | mouse-perturb-4tf | 313504a | excel_demangle |
| #142 | dynamic_convergence | 13f8dad | excel_demangle + strip_make_unique |
| #145 | brain_organoid_atlas | e9e4efd | excel_demangle + strip_make_unique |
| #143 | polygenic-risk-20 | 2663b50 | excel_demangle + strip_make_unique |
| #140 | psychscreen | 8137be3 | excel_demangle + strip_make_unique + split_symbol_ensg |
| #144 | hsc-asd-organoid-m5 | b2e7d2a | excel_demangle + strip_make_unique (xlsx-side; Tier-A verification deferred to wrangler re-run) |

These commits are on `main`. (`#142` is pushed; `e9e4efd / 2663b50 / 8137be3 / b2e7d2a` are local-only at last check — verify with `git log origin/main..HEAD`.)

While doing those migrations, four design problems surfaced. This plan addresses all four together.

### Problem 1 — `ignore_missing:` is overloaded

The current YAML knob is being used for at least four conceptually different cases:

- Clinical placeholders: `not_available`, `none identified`
- Synthetic / control reagents: `GFP`, `NonTarget1`, `SafeTarget`, `Control_ST`, `Gm16091`
- Retired HGNC symbols with known canonical successors: `NOV` → `CCN3`, `QARS` → `QARS1`, `MUM1` → `PWWP3A`, `TAZ` → `TAFAZZIN`, `SARS` → `SARS1`
- Retired HGNC symbols with no successor / pseudogene relics: `SGK494`, `GATD3B`, `IQCD`, `IQCA1`, `CRIPAK`, `U2AF1L5`, `SMC5-AS1`, `OCLM`, `SMIM11B`, …

A wrangler reading `ignore_missing: [NOV, GFP, not_available, SGK494]` cannot tell what's happening to each row.

### Problem 2 — `ignore_missing` silently drops data

Real code at [processing/src/processing/types/gene_mapping.py:104-122](processing/src/processing/types/gene_mapping.py#L104):

```python
if gene_val not in species_map:
    if gene_val in self.ignore_missing:
        data_id_to_central_gene_id.append((row_id, None))
        continue                                       # <- skips central_gene insertion entirely
    if is_non_symbol_identifier(gene_val) is None:
        get_sspsygene_logger().warning(...)            # warn unless Tier B silences
    new_entry = get_central_gene_table().add_species_entry(...)
    species_map[gene_val] = [new_entry]
```

`ignore_missing` symbols get **no warning AND no central_gene row**. Empirically verified by `SELECT * FROM central_gene WHERE human_symbol = 'NOV'` returning zero rows even when `dynamic_convergence_S2` has a `NOV` row.

The YAML comments propagated across `#125` / `#140` / `#142` / `#143` / `#144` / `#145` ("rows still added to central_gene as manual entries") are therefore **incorrect for the current code state**. They were aspirational/wrong and copy-pasted.

`#121`'s body promises an even more destructive future ("wranglers drop unwanted rows in preprocess"). The user (jbirgmei) has explicitly asked to **keep `ignore_missing`'s spirit** but make it actually do what the comments said: silence the warning AND insert a `manually_added=1` stub.

### Problem 3 — retired HGNC symbols are AMBIGUOUS

Empirically verified against `data/homology/hgnc_complete_set.txt`:

| Retired symbol | Approved symbols claiming it as prev/alias |
|---|---|
| NOV | CCN3 (prev), RPL10 (alias), PLXNA1 (alias) |
| QARS | QARS1 (prev), EPRS1 (prev) |
| MUM1 | IRF4 (prev), PWWP3A (prev) |
| SARS | SARS1 (prev), SARS2 (alias) |
| TAZ | TAFAZZIN (prev), WWTR1 (alias) |
| MPP6 | MPHOSPH6 (alias), PALS2 (prev) |
| C18orf21 | RMP24 (prev), RMP24P1 (prev) |
| SGK494 | (none — truly retired) |
| GATD3B | (none — truly retired) |

The normalizer's `_load_hgnc()` ([processing/src/processing/preprocessing/symbol_index.py:111-114](processing/src/processing/preprocessing/symbol_index.py#L111)) correctly drops ambiguous aliases:

```python
for alias, symbols in alias_to_symbols.items():
    if len(symbols) == 1:
        self.human_alias_to_symbol[alias] = next(iter(symbols))
```

So `normalizer.resolve("NOV", "human")` returns `None`, not `"CCN3"`. **Auto-resolution can't pick the right successor — a wrangler must decide per dataset.**

### Problem 4 — `clean_gene_column` overwrites the original column

[processing/src/processing/preprocessing/dataframe.py:149](processing/src/processing/preprocessing/dataframe.py#L149) replaces `df[column]` with cleaned values. Wranglers can't audit what rescue happened on a row from the TSV alone. Every dataset's `preprocess.py` then drops the `_<col>_resolution` annotation column before write, so even the per-row tag is gone.

Grep across all `data/datasets/*/preprocess.py` confirms: nobody preserves the raw value today.

### Problem 5 (smaller) — link-table asymmetry bug

In the gene_mapping.py loop above, when an unknown symbol is FIRST encountered: `add_species_entry()` runs but `(row_id, entry.row_id)` is **not appended** to `data_id_to_central_gene_id`. Subsequent rows hitting the same symbol get linked via the `else` branch on line 124. So the very first row with a never-before-seen unresolved symbol is orphaned. This is almost certainly a bug.

## 2. Current state — concrete details

### 2.1 Pipeline trace

`sq_load.py:523` calls `load_gene_tables()` → `central_gene_table.py:399-404` builds the singleton `CentralGeneTable` via three passes:
1. `parse_hgnc()` reads `data/homology/hgnc_complete_set.txt` — populates `human_symbol`, `human_entrez_gene`, `hgnc_id`, `human_synonyms` (= retired prev_symbols).
2. `parse_mgi_homology()` reads the Alliance file — builds MGI→HGNC and MGI→Ensembl maps.
3. `parse_mgi()` reads `MGI_EntrezGene.rpt` — attaches `mouse_symbols`, `mouse_mgi_accession_ids`, `mouse_ensembl_genes` to existing human entries; creates mouse-only entries for orphans.

Manually-added rows ([central_gene_table.py:179-187](processing/src/processing/central_gene_table.py#L179)) carry **only the symbol**; `human_entrez_gene=None`, `human_ensembl_gene=None`, `hgnc_id=None`, `manually_added=True`.

`ensembl_to_symbol` is built by [processing/src/processing/ensembl_symbol_table.py:18-70](processing/src/processing/ensembl_symbol_table.py#L18) from `central_gene_table` entries that have both a Ensembl ID and a symbol. Used at API serve time by [web/lib/ensembl-symbol-resolver.ts](web/lib/ensembl-symbol-resolver.ts) to substitute ENSG IDs in API responses with symbols (`#119` plans to move this to preprocess time).

`extra_gene_synonyms` is built at [sq_load.py:125-138](processing/src/processing/sq_load.py#L125) from `entry.human_synonyms ∩ entry.used_human_names` — only synonyms that actually appeared in some dataset are stored. So `NOV → CCN3` is in `extra_gene_synonyms` only if some dataset had a `NOV` row (which several do; query `SELECT synonym FROM extra_gene_synonyms WHERE synonym='NOV'` returns hits).

### 2.2 Per-dataset YAML knob inventory

Datasets under `data/datasets/`: `brain_organoid_atlas`, `dynamic_convergence`, `hsc-asd-organoid-m5`, `mgi_phenotypes`, `mouse-perturb-4tf`, `perturb-fish`, `phenome_jax`, `polygenic-risk-20`, `psychscreen`, `sfari`, `zebraAsd`. (Plus `globals.yaml`.)

| Knob | Datasets using it |
|---|---|
| `ignore_missing:` | brain_organoid_atlas, dynamic_convergence, hsc-asd-organoid-m5, mouse-perturb-4tf, perturb-fish, polygenic-risk-20, psychscreen, sfari |
| `replace:` | dynamic_convergence (2 trailing-dot fixes: `ABALON. → ABALON`, `SGK494. → SGK494`), zebraAsd (1 ortholog rename: `SCN1LAB → SCN1A`) |
| `to_upper:` | zebraAsd only |
| `multi_gene_separator:` | hsc-asd-organoid-m5 only (region_genes column, comma-separated) |
| `ignore_empty:` | hsc-asd-organoid-m5 (3 mappings), mgi_phenotypes |
| Unfamiliar: `gene_type: ensmus` | mgi_phenotypes — flag for ensembl-mouse-ID column |
| Unfamiliar: `comment:` | perturb-fish — inert documentation, ignored by parser |

Datasets with `preprocess.py`: brain_organoid_atlas, dynamic_convergence, hsc-asd-organoid-m5, mouse-perturb-4tf, polygenic-risk-20, psychscreen.
Datasets WITHOUT `preprocess.py`: mgi_phenotypes, perturb-fish, sfari, zebraAsd.

### 2.3 Tickets snapshot (all in `sspsygene-dracc/psypheno`)

- **#119** OPEN — Move ENSG→symbol conversion from API request-time to per-dataset preprocessing.
- **#120** OPEN (work done) — Shared preprocessing utilities library at `processing/src/processing/preprocessing/`. Ships `GeneSymbolNormalizer`, `excel_demangle`, `strip_make_unique_suffix`, `split_symbol_ensg`, `resolve_hgnc_id`, `is_non_symbol_identifier`, `clean_gene_column` DataFrame wrapper.
- **#121** OPEN — *Migrate gene-name normalization out of load-db.* Currently promises to retire `to_upper` / `multi_gene_separator` / `replace:` / `ignore_missing:`. **Lands last per its body — but this plan rewrites it.**
- **#122** OPEN (helper landed) — Tier A: `excel_demangle`. Per-dataset migrations split out as `#142–#146`.
- **#123** OPEN (helper landed) — Tier B: `is_non_symbol_identifier` silencer. Default-on for ENSG / ENSMUSG / contig / gencode_clone / genbank_accession.
- **#124** OPEN (helpers landed) — Tier C: `resolve_hgnc_id` (C1), `strip_make_unique_suffix` (C2), `split_symbol_ensg` (C3).
- **#125** CLOSED — Tier D refresh attempt; closed because most "unmapped" symbols are genuinely retired by HGNC.
- **#126** OPEN — Tracker.
- **#139** OPEN, deferred — Tier C4: GENCODE clone resolution (needs new GTF data source).
- **#140** CLOSED — psychscreen.
- **#141** CLOSED obsolete — geschwind_2026_cnv merged into hsc-asd-organoid-m5.
- **#142** CLOSED — dynamic_convergence.
- **#143** CLOSED — polygenic-risk-20.
- **#144** CLOSED — hsc-asd-organoid-m5.
- **#145** CLOSED — brain_organoid_atlas.
- **#146** CLOSED — mouse-perturb-4tf (the reference pattern).

The close comments on #140 / #142 / #143 / #144 / #145 each say "ignore_missing was a temporary measure; cleanup continues under #121." That framing now needs revision per this plan — `ignore_missing`'s spirit stays, only the YAML name and dispatch change.

## 3. Design (user-locked choices)

The user has confirmed all four design choices below.

### 3.1 New YAML schema for un-resolvable values

Replace `ignore_missing:` and `replace:` with one grouped block:

```yaml
gene_mappings:
  - column_name: target_gene
    species: human
    link_table_name: gene
    perturbed_or_target: target
    non_resolving:
      drop_values: [not_available, NonTarget1, GFP]      # literal strings → orphan link, no central_gene entry, no warn
      drop_patterns: [ensembl_human, gencode_clone]      # pattern category names → orphan link, no central_gene entry, no warn
      record_values: [SGK494, GATD3B]                    # literal strings → central_gene stub w/ manually_added=1, no warn
      record_patterns: [genbank_accession, contig]       # pattern category names → stub, no warn
```

Pattern category names map to existing predicates in [preprocessing/helpers.py](processing/src/processing/preprocessing/helpers.py)'s `NonSymbolCategory` literal: `ensembl_human`, `ensembl_mouse`, `contig`, `gencode_clone`, `genbank_accession`. Expose them as a public `NON_SYMBOL_CATEGORIES` constant for the YAML loader to validate against.

**Default behavior with no `non_resolving:` block**: any unresolved value emits a warning AND creates a `manually_added=1` stub (the new strict-by-default behavior). The current implicit Tier B silencing goes away — wranglers must explicitly opt in via `record_patterns:` per dataset. One-time migration cost; makes silencing auditable.

### 3.2 Row-drop policy: explicit only

No `preprocess.py` may silently drop rows from a source file. Every dropped row must be accounted for via:

- `drop_values:` / `drop_patterns:` in the YAML (preferred), OR
- `ignore_empty:` (existing, for blank values), OR
- A documented dataset-specific transformation in `preprocess.py` whose docstring calls it out AND emits a count to stdout.

The known offender to retire: [hsc-asd-organoid-m5/preprocess.py:86-87](data/datasets/hsc-asd-organoid-m5/preprocess.py#L86) `dropna(subset=["hgnc_symbol"])` silently throws away ~87,435 rows per Supp 3 read. Those rows should pass through; `non_resolving:` decides their fate.

### 3.3 Cleaner preserves raw values + supports manual aliases

`clean_gene_column` API change in [processing/src/processing/preprocessing/dataframe.py](processing/src/processing/preprocessing/dataframe.py):

- **Move raw to `<col>_raw`, clean stays in `<col>`.** Existing `column_name:` references in YAML continue to work unchanged. Resolution-tag column `_<col>_resolution` remains as today.
- **New `manual_aliases: dict[str, str]` parameter**, e.g. `{"NOV": "CCN3", "QARS": "QARS1", "MUM1": "PWWP3A"}`. Applied AFTER all auto-rescues (`excel_demangle`, `strip_make_unique`, `split_symbol_ensg`, `resolve_hgnc_id`) fail, BEFORE `is_non_symbol_identifier` classification. Tagged `rescued_manual_alias` in the resolution column. Resolves through the normalizer (so `NOV → CCN3` only succeeds if `CCN3` is a current approved symbol — guards against typos).
- **ENSG/GenBank → symbol via the `ensembl_to_symbol` map** at preprocess time becomes a future `resolve_via_ensembl_map: bool` flag (per `#119`). Out of scope for the schema PR; standalone follow-up.

### 3.4 Strict load-db dispatch

Rewrite the per-row resolution loop in `gene_mapping.py:resolve_to_central_gene_table()`:

1. `ignore_empty` (existing) → orphan, no further work
2. `multi_gene_separator` split (existing — stays at load-db; preprocess-time split would corrupt row IDs)
3. Resolve in `central_gene` species_map → join, append `(row_id, entry.row_id)`
4. **NEW**: value in `drop_values` OR matches a `drop_patterns` category → orphan link `(row_id, None)`, no stub, no warn
5. **NEW**: value in `record_values` OR matches a `record_patterns` category → create stub via `add_species_entry()`, append link `(row_id, new_entry.row_id)`, no warn
6. **Default fallback** → WARN + create stub + append link

**Concurrent fix**: in step 6 (and 5), append `(row_id, new_entry.row_id)` so the first-encounter row is linked. Fixes Problem 5 above.

`replace:`, `to_upper:` retire from `GeneMapping`. Wranglers do these in `preprocess.py` via `clean_gene_column`'s `manual_aliases` (for replace-style str→str) or trivial pandas ops (`df[col].str.upper()`). The 3 existing `replace:` entries migrate to:
- `dynamic_convergence`: `ABALON. → ABALON`, `SGK494. → SGK494` → preprocess.py via a per-call `manual_aliases={"ABALON.": "ABALON", "SGK494.": "SGK494"}` (or a future trailing-dot helper).
- `zebraAsd`: `SCN1LAB → SCN1A` → preprocess.py via `manual_aliases={"SCN1LAB": "SCN1A"}`.

`multi_gene_separator:` stays at load-db (not promoted to preprocess.py) — splitting at preprocess time would change dataset row counts and break upstream paper IDs.

### 3.5 Execution shape (user-locked)

Library + new YAML schema first; per-dataset migrations follow. Concretely: one PR ships the library + schema changes (sections 3.1, 3.3, 3.4) including the link-table asymmetry fix, behind no behavior change for existing datasets (`ignore_missing` continues to be parsed during the transition with a deprecation warning that maps it to the equivalent of `record_values:` so the comments-vs-code discrepancy is finally fixed). Then 9 small per-dataset migration PRs convert `ignore_missing` → `non_resolving:` blocks one dataset at a time.

## 4. Per-dataset migration table

Re-classify every current `ignore_missing` entry. The wrangler-side job per dataset.

| Today's bucket | New home | Examples |
|---|---|---|
| Clinical placeholders | `drop_values:` | `not_available`, `none identified` |
| Synthetic / control reagents | `drop_values:` | `GFP`, `NonTarget1`, `SafeTarget`, `Control_ST`, `Gm16091`, `Gm42864` |
| Retired-with-known-successor | `manual_aliases={...}` in `preprocess.py` | `NOV → CCN3`, `QARS → QARS1`, `MUM1 → PWWP3A`, `TAZ → TAFAZZIN`, `SARS → SARS1`, `MPP6 → ?`, `DEC1 → BHLHE40 or DELEC1`, `LOR → ?` |
| Retired-no-successor | `record_values:` | `SGK494`, `GATD3B`, `IQCD`, `IQCA1`, `CRIPAK`, `U2AF1L5`, `SMC5-AS1`, `OCLM`, `SMIM11B`, `TMEM155`, `SMIM34B`, `KCNE1B`, `THRA1/BTR`, `CBSL`, `TEMN3-AS1`, `ABALON`, `FAM243B`, `FLJ45513`, `HGC6.3`, `SIK1B`, `LINC00283`, `DUSP27` |
| Old aliases / RNA family / antisense | `record_values:` | `HDGFRP3`, `HDGFRP2`, `LYST-AS1`, `Y_RNA`, `MIR5096`, `SNORA74`, `MSNP1AS`, `RPS10P2-AS1` |
| Tier B regex categories | `record_patterns:` (explicit opt-in) | `[ensembl_human, ensembl_mouse, contig, gencode_clone, genbank_accession]` per dataset that has those |

The wrangler decides per-dataset whether NOV → CCN3 is right in their paper's context. For NDD-focused datasets in this repo, `CCN3` is the right call for NOV (it's the matrix protein). The MPP6/LOR/DEC1 mappings need wrangler / domain-expert review before commit.

## 5. File-level changes

### Library + schema PR (lands first)

- [processing/src/processing/preprocessing/dataframe.py](processing/src/processing/preprocessing/dataframe.py) — `clean_gene_column` emits `<col>_raw`, accepts `manual_aliases`. New `rescued_manual_alias` resolution tag. Existing rescue order preserved.
- [processing/src/processing/types/gene_mapping.py](processing/src/processing/types/gene_mapping.py) — parse `non_resolving:` block; new dispatch order; fix link-table asymmetry; deprecation-warning path for `ignore_missing:` / `replace:` / `to_upper:` so existing configs still work during the transition.
- [processing/src/processing/preprocessing/helpers.py](processing/src/processing/preprocessing/helpers.py) — expose `NON_SYMBOL_CATEGORIES: dict[str, Callable[[str], bool]]` for YAML loader to validate.
- [processing/src/processing/preprocessing/__init__.py](processing/src/processing/preprocessing/__init__.py) — re-export.
- New unit tests for: `manual_aliases` rescue, raw-column preservation, the four `non_resolving:` paths, link-table asymmetry fix, deprecation path for old knobs.

### Per-dataset migration PRs (one per dataset, after the library PR)

For each of the 9 datasets that use the soon-deprecated knobs:

1. Migrate `config.yaml`: `ignore_missing:` / `replace:` / `to_upper:` → `non_resolving:` block (and/or `manual_aliases` invocation in `preprocess.py`).
2. Add `preprocess.py` if missing — needed for: `mgi_phenotypes`, `perturb-fish`, `sfari`, `zebraAsd`.
3. Pass `manual_aliases` for retired-with-successor symbols.
4. Drop the per-dataset YAML comment "rows still added to central_gene as manual entries" — it's now actually true after the library PR ships, but the new comment text in `non_resolving:` blocks should be self-explanatory.
5. Side-car DB rebuild + per-criteria verification (see section 7).

## 6. Ticket changes

- **#121 — full rewrite.** New title: *"Replace `ignore_missing`/`replace`/`to_upper` with explicit `non_resolving:` block and `manual_aliases:`"*. Body describes the new 4-knob schema, the `manual_aliases` parameter, raw-column preservation. Acceptance: every `ignore_missing` entry across the repo classified into one of the new buckets; old knobs removed from `GeneMapping`.
- **#119 — unchanged but cross-referenced.** Continues to track ENSG → symbol conversion at preprocess time (the future `resolve_via_ensembl_map` flag).
- **#126 — update tracker.** Reflect closed sub-tickets; add a new sub-task "non_resolving schema migration" (parent of the 9 per-dataset migrations).
- **#140 / #142 / #143 / #144 / #145 — add follow-up comments.** Note that `ignore_missing`'s spirit (silence + record stub) is preserved under the new `non_resolving.record_values:` knob; the past close comments asserting "rows still added to central_gene as manual entries" become accurate once the library PR ships (today they're aspirational/wrong).
- **New ticket: link-table asymmetry fix.** Lands with the library PR.
- **New ticket: deprecation of implicit Tier B silencing.** Flags the migration cost — datasets that today rely on hardcoded `is_non_symbol_identifier` need explicit `record_patterns:` after the schema change.
- **New ticket: retire silent `preprocess.py` row-drops.** Audit every existing `preprocess.py` for `dropna()`, boolean-mask filters, and similar; either move to YAML config or surface the drop count + reason in the script's stdout. Concrete known offender: [hsc-asd-organoid-m5/preprocess.py:86-87](data/datasets/hsc-asd-organoid-m5/preprocess.py#L86).
- **New ticket: track dropped/skipped rows in download-page metadata.** Wranglers and downstream users should be able to see, per dataset, how many rows were dropped and why (which `drop_values:` entry or `drop_patterns:` category triggered, or `ignore_empty:`, or a documented preprocess-time dropna). Implementation sketch: `load-db` emits a per-dataset `drop_audit.tsv` (columns: `dataset`, `table`, `column`, `reason`, `value`, `row_count`) into `data/db/exports/`; the [downloads page](web/pages/downloads.tsx) lists it alongside the existing artifacts. Out of scope for the schema PR; standalone follow-up.
- **New ticket: end-to-end test for row-drop accounting.** Once `#117`'s test infrastructure exists (currently no automated suite — see CLAUDE.md), add a regression test that verifies two invariants: (1) for every dataset, `(input rows) − (rows present in dataset table) − (rows present in drop_audit.tsv) == 0` — i.e. no row vanishes silently; (2) every row in `drop_audit.tsv` traces to a specific `non_resolving:` entry, `ignore_empty:` flag, or whitelisted preprocess-time transform. Catches regressions where a wrangler adds a silent `dropna()` to `preprocess.py` or a YAML knob misclassifies. Depends on the drop-audit ticket above; independent of the schema PR.

## 7. Verification

Per the project's [CLAUDE.md](CLAUDE.md), use the side-car DB rebuild rather than the default DB path:

```bash
sed 's|"db/sspsygene.db"|"db/sspsygene-claude.db"|' \
    processing/src/processing/config.json > /tmp/sspsygene-config-claude.json
SSPSYGENE_DATA_DIR=/Users/jbirgmei/prog/sspsygene/data \
SSPSYGENE_CONFIG_JSON=/tmp/sspsygene-config-claude.json \
    processing/.venv-claude/bin/sspsygene load-db --dataset NAME
```

After each per-dataset migration, verify:

1. **Row counts**: `central_gene` row count diff vs main is exactly the expected delta (new `manually_added=1` stubs from `record_values` / `record_patterns`, minus any orphans that previously got stubs but now `drop_values`/`drop_patterns`).
2. **Zero unaccounted warnings**: `sspsygene load-db --dataset NAME 2>&1 | grep "not in gene maps"` returns empty for every value listed under `non_resolving:`.
3. **manual_aliases rescues join correctly**: `sqlite3 data/db/sspsygene-claude.db` — for each rescued symbol (e.g. `NOV → CCN3`), confirm the dataset table's link points to `CCN3`'s `central_gene` row, which has full HGNC + MGI homology.
4. **`<col>_raw` preserved in TSV**: spot-check the cleaned TSV for at least one row per resolution tag (`passed_through`, `rescued_excel`, `rescued_manual_alias`, `rescued_make_unique`, `non_symbol_*`) — `<col>_raw` matches the pre-cleaner value, `<col>` shows the canonical form.
5. **Library-side**: pytest covers the new dispatch order, `manual_aliases`, raw-column preservation, link-table asymmetry fix, deprecation path.

End-to-end smoke after all 9 datasets migrate: full DB rebuild (`sspsygene load-db` no `--dataset`), confirm row counts match the pre-migration baseline ± documented deltas. Run `npx tsc --noEmit` in `web/` (the canonical pre-commit check per CLAUDE.md).

## 8. Out of scope

- ENSG → symbol conversion at preprocess time (`#119`'s remaining work).
- GENCODE clone resolution (`#139`, deferred — needs GTF data source).
- Removing `manually_added=1` stubs from `central_gene` for "junk" categories (e.g. ENSG IDs that already exist as approved symbols) — that's a separate cleanup orthogonal to this redesign.
