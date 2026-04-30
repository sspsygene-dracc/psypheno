# Redesign gene-name normalization architecture (sspsygene)

> **For a fresh agent:** this plan is fully self-contained. Read this top-to-bottom before exploring. The repo is `/Users/jbirgmei/prog/sspsygene` (code) and `sspsygene-dracc/psypheno` (issue tracker — separate GitHub repo, use `gh` against it). Project context is in [CLAUDE.md](CLAUDE.md).

> **Status (2026-04-30):** library + schema + all per-dataset migrations landed in a single working-tree change. No PRs opened yet; no DB rebuild run yet. The follow-up tickets from §6 were intentionally NOT filed per user direction. See §9 ("Implementation log") at the bottom for deltas vs. the original design.

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

> **Status:** the silent dropna in hsc-asd-organoid-m5/preprocess.py is **still in place** after this implementation. It was scoped out and remains a known offender; the wrangler should let those rows through and rely on `non_resolving:` next time the dataset is re-loaded.

### 3.3 Cleaner preserves raw values + supports manual aliases

`clean_gene_column` API change in [processing/src/processing/preprocessing/dataframe.py](processing/src/processing/preprocessing/dataframe.py):

- **Move raw to `<col>_raw`, clean stays in `<col>`.** Existing `column_name:` references in YAML continue to work unchanged. Resolution-tag column `_<col>_resolution` remains as today. The cleaner **raises `KeyError`** if `<col>_raw` already exists in the input frame, so the wrangler must rename or drop the conflicting column before calling.
- **New `manual_aliases: dict[str, str]` parameter**, e.g. `{"NOV": "CCN3", "QARS": "QARS1", "MUM1": "PWWP3A"}`. Applied AFTER all auto-rescues (`excel_demangle`, `strip_make_unique`, `split_symbol_ensg`, `resolve_hgnc_id`) fail, BEFORE `is_non_symbol_identifier` classification. Tagged `rescued_manual_alias` in the resolution column. The target **must** resolve through the normalizer to a current approved symbol; if not, the cleaner **raises `ValueError`** (rather than silently dropping the alias). This makes manual_aliases unsuitable for "fix a typo to a value that itself isn't a real symbol" — those need a pandas op upstream of the cleaner (e.g. `df[col].str.rstrip(".")`, see §4 dynamic_convergence).
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

`ignore_missing:`, `replace:`, `to_upper:` retire from `GeneMapping` and **hard-error on parse** (no deprecation path; this implementation migrated all callers in the same change). Wranglers do replace/to_upper in `preprocess.py` via `clean_gene_column`'s `manual_aliases` (for str→str rescues whose target is a real symbol) or trivial pandas ops. The 3 existing `replace:` entries migrate to:
- `dynamic_convergence`: `ABALON. → ABALON`, `SGK494. → SGK494` → **pandas `df[col].str.rstrip(".")`** in preprocess.py. NOT manual_aliases, because manual_aliases requires the target to resolve through the normalizer and `ABALON` / `SGK494` are themselves retired-no-successor symbols (handled via `record_values:` in YAML).
- `zebraAsd`: `SCN1LAB → SCN1A` → preprocess.py via a custom `transform_sample()` that upper-cases and substitutes (covers both `to_upper:` and `replace:` for that file in one pass; the column is later split by load-db's `split_column_map`).

`multi_gene_separator:` stays at load-db (not promoted to preprocess.py) — splitting at preprocess time would change dataset row counts and break upstream paper IDs.

### 3.5 Execution shape

**Final shape (what shipped):** one combined working-tree change. Library + schema + every per-dataset migration land together. Retired keys (`ignore_missing` / `replace` / `to_upper`) hard-error in `GeneMapping.from_json`; there is no deprecation window. The original plan called for staged PRs with a deprecation path, but the user explicitly opted to remove the soon-deprecated code outright since it was all introduced recently and every caller in the repo could be migrated in the same diff.

## 4. Per-dataset migration table

Re-classify every current `ignore_missing` entry. The wrangler-side job per dataset.

| Today's bucket | New home | Examples |
|---|---|---|
| Clinical placeholders | `drop_values:` | `not_available`, `none identified` |
| Synthetic / control reagents | `drop_values:` | `GFP`, `NonTarget1`, `SafeTarget`, `Control_ST`, `Gm16091`, `Gm42864` |
| Retired-with-known-successor (high-confidence) | `manual_aliases={...}` in `preprocess.py` | `NOV → CCN3`, `QARS → QARS1`, `MUM1 → PWWP3A`, `TAZ → TAFAZZIN`, `SARS → SARS1` |
| Retired-with-known-successor (needs review) | `record_values:` (parked pending wrangler/domain-expert input) | `MPP6`, `LOR`, `DEC1` |
| Retired-no-successor | `record_values:` | `SGK494`, `GATD3B`, `IQCD`, `IQCA1`, `CRIPAK`, `U2AF1L5`, `SMC5-AS1`, `OCLM`, `SMIM11B`, `TMEM155`, `SMIM34B`, `KCNE1B`, `THRA1/BTR`, `CBSL`, `TEMN3-AS1`, `ABALON`, `FAM243B`, `FLJ45513`, `HGC6.3`, `SIK1B`, `LINC00283`, `DUSP27`, `C18orf21` (ambiguous prev-symbol) |
| Old aliases / RNA family / antisense | `record_values:` | `HDGFRP3`, `HDGFRP2`, `LYST-AS1`, `Y_RNA`, `MIR5096`, `SNORA74`, `MSNP1AS`, `RPS10P2-AS1` |
| Tier B regex categories | `record_patterns:` (explicit opt-in) | `[ensembl_human, ensembl_mouse, contig, gencode_clone, genbank_accession]` per dataset that has those |

For NDD-focused datasets in this repo, `CCN3` is the right call for NOV (it's the matrix protein), and similarly the QARS1 / PWWP3A / TAFAZZIN / SARS1 successors were applied across the migrated datasets. The `MPP6 / LOR / DEC1` mappings remain parked in `record_values:` — domain-expert input still required before promoting them to `manual_aliases`.

> **Status:** all eight datasets that used `ignore_missing` have been migrated to this taxonomy. No `record_patterns:` entries were added in this round — the implicit Tier B silencing turning into per-dataset opt-in is a behavior change that surfaces as load-db warnings the next time a wrangler rebuilds. That's intentional (see §3.1).

## 5. File-level changes

### Library + schema (landed)

- [processing/src/processing/preprocessing/dataframe.py](processing/src/processing/preprocessing/dataframe.py) — `clean_gene_column` emits `<col>_raw`, accepts `manual_aliases`. New `rescued_manual_alias` resolution tag. Existing rescue order preserved. Raises `KeyError` if `<col>_raw` already exists; raises `ValueError` if a `manual_aliases` target doesn't resolve through the normalizer.
- [processing/src/processing/types/gene_mapping.py](processing/src/processing/types/gene_mapping.py) — new `NonResolving` dataclass; parses `non_resolving:` block; new dispatch order; fixes the link-table asymmetry. **Hard-errors** (no deprecation path) on the retired keys `ignore_missing` / `replace` / `to_upper`, and on the long-retired `is_perturbed` / `is_target`.
- [processing/src/processing/preprocessing/helpers.py](processing/src/processing/preprocessing/helpers.py) — exposes `NON_SYMBOL_CATEGORIES: dict[str, Callable[[str], bool]]` for the YAML loader to validate `drop_patterns` / `record_patterns` entries.
- [processing/src/processing/preprocessing/__init__.py](processing/src/processing/preprocessing/__init__.py) — re-exports.
- Tests:
  - [tests/preprocessing/test_dataframe.py](processing/tests/preprocessing/test_dataframe.py) — `<col>_raw` preservation, raw-column collision, manual_aliases rescue, unresolvable-target raise, rescue ordering.
  - [tests/preprocessing/test_helpers.py](processing/tests/preprocessing/test_helpers.py) — `NON_SYMBOL_CATEGORIES` shape + per-category predicate.
  - [tests/processing_types/test_gene_mapping.py](processing/tests/processing_types/test_gene_mapping.py) — new file; covers `NonResolving` parsing/validation/classify, `GeneMapping` rejection of retired keys, dispatch order (drop / record / fallback), link-table asymmetry fix, stub creation. (Directory named `processing_types/` rather than `types/` to avoid shadowing the `types` stdlib module during pytest collection.)

### Per-dataset migrations (landed)

All in the same change. Per dataset, one or more of:

1. `config.yaml`: `ignore_missing:` / `replace:` / `to_upper:` (and empty `ignore_missing: []` no-ops) → `non_resolving:` block, with the column's mapping order tightened to put `perturbed_or_target:` adjacent to its category.
2. `preprocess.py`: pass `manual_aliases` for high-confidence retired-with-successor symbols (NOV/QARS/MUM1/TAZ/SARS subsets per dataset). Raw column `<col>_raw` is kept in the output TSV; `_<col>_resolution` is dropped before write.
3. New `preprocess.py` for `zebraAsd` (covers `to_upper:` + `replace: SCN1LAB → SCN1A` → `transform_sample()` that splits on `_`, upper-cases gene token, applies the ortholog rename). Generated `*_cleaned.txt` is committed.
4. The misleading "rows still added to central_gene as manual entries" YAML comments were dropped; the new `non_resolving.record_values:` comments explain stub creation explicitly.
5. Side-car DB rebuild — **not yet run** in this iteration. Pytest passes (139/139) and `npx tsc --noEmit` is clean.

Datasets that still **don't** have a `preprocess.py` and didn't need one: `mgi_phenotypes`, `perturb-fish`, `sfari` — their migrations are YAML-only because they had no `to_upper` / `replace` / mapping requiring a manual alias.

## 6. Ticket changes — DEFERRED

**The user explicitly opted not to file follow-up tickets in this round.** Keeping the original list below for record-keeping and so a future agent can re-evaluate when filing them is appropriate (e.g. before opening a PR for this work).

- **#121 — full rewrite.** New title: *"Replace `ignore_missing`/`replace`/`to_upper` with explicit `non_resolving:` block and `manual_aliases:`"*. Body describes the new 4-knob schema, the `manual_aliases` parameter, raw-column preservation. Acceptance: every `ignore_missing` entry across the repo classified into one of the new buckets; old knobs removed from `GeneMapping`. (All acceptance criteria are now met by the landed change.)
- **#119 — unchanged but cross-referenced.** Continues to track ENSG → symbol conversion at preprocess time (the future `resolve_via_ensembl_map` flag).
- **#126 — update tracker.** Reflect closed sub-tickets.
- **#140 / #142 / #143 / #144 / #145 — add follow-up comments.** Note that `ignore_missing`'s spirit (silence + record stub) is preserved under the new `non_resolving.record_values:` knob; the past close comments asserting "rows still added to central_gene as manual entries" are now accurate (they were aspirational/wrong before).
- **New ticket: deprecation of implicit Tier B silencing** — datasets that today rely on hardcoded `is_non_symbol_identifier` need explicit `record_patterns:` after the schema change. This change has SHIPPED in the implementation; new warning spam will surface on the next dataset rebuild.
- **New ticket: retire silent `preprocess.py` row-drops.** Audit every existing `preprocess.py` for `dropna()`, boolean-mask filters, and similar. Concrete known offender still in place: [hsc-asd-organoid-m5/preprocess.py:86-87](data/datasets/hsc-asd-organoid-m5/preprocess.py#L86).
- **New ticket: track dropped/skipped rows in download-page metadata** (drop_audit.tsv).
- **New ticket: end-to-end test for row-drop accounting.**

## 7. Verification

### What's verified so far

- **Library-side pytest** — 139/139 passing, including 27 new tests covering: `<col>_raw` preservation, raw-column collision, manual_aliases rescue + unresolvable-target raise, rescue ordering, `NON_SYMBOL_CATEGORIES` shape + predicates, `NonResolving` parsing/validation/classify, `GeneMapping` rejection of retired keys, full dispatch order (drop / record / fallback), and the link-table asymmetry fix.
- **YAML config parse** — every `gene_mapping` block across the 10 dataset YAMLs parses cleanly through the new `GeneMapping.from_json` (verified via a small one-off script during implementation).
- **web `npx tsc --noEmit`** — clean, as expected (no spillover into the TS surface).

### What still needs to be verified (deferred to user)

Per the project's [CLAUDE.md](CLAUDE.md), use the side-car DB rebuild rather than the default DB path. **The user has not run this yet** — the implementation explicitly stops short of touching `data/db/sspsygene.db`.

```bash
sed 's|"db/sspsygene.db"|"db/sspsygene-claude.db"|' \
    processing/src/processing/config.json > /tmp/sspsygene-config-claude.json
SSPSYGENE_DATA_DIR=/Users/jbirgmei/prog/sspsygene/data \
SSPSYGENE_CONFIG_JSON=/tmp/sspsygene-config-claude.json \
    processing/.venv-claude/bin/sspsygene load-db --dataset NAME
```

Per-dataset checks once that runs:

1. **Row counts**: `central_gene` row count diff vs main is exactly the expected delta. **Direction reverses vs the original plan**: each migration ADDS `manually_added=1` stubs for entries that today are silently orphaned via `ignore_missing`. Orphan rows newly classified as `drop_values`/`drop_patterns` see no row count change (they were already orphans). `manual_aliases` rescues subtract from the stub count and instead link to existing HGNC entries.
2. **Zero unaccounted warnings**: `sspsygene load-db --dataset NAME 2>&1 | grep "not in gene maps"` should be empty for every value covered by `non_resolving:`. Datasets that historically relied on Tier B silencing for raw ENSG/contig/etc IDs WILL produce new warnings until `record_patterns:` entries are added — this is the intentional behavior change called out in §3.1.
3. **manual_aliases rescues join correctly**: for each rescued symbol (e.g. `NOV → CCN3`), confirm the dataset table's link points to `CCN3`'s `central_gene` row.
4. **`<col>_raw` preserved in TSV**: spot-check the cleaned TSV for at least one row per resolution tag — `<col>_raw` matches the pre-cleaner value, `<col>` shows the canonical form. (Existing `*_cleaned.csv/tsv` outputs in the repo were generated by the OLD preprocess.py and lack `<col>_raw`; they'll gain the column the next time a wrangler runs preprocess.py.)
5. **zebraAsd**: the regenerated `1-s2.0-S2211124723002541-mmc5_cleaned.txt` was produced by the new preprocess.py during implementation and is committed; load-db should consume it without error.

End-to-end smoke once all datasets are rebuilt: full DB rebuild (`sspsygene load-db`, no `--dataset`), confirm row counts match the pre-migration baseline ± documented deltas.

## 8. Out of scope

- ENSG → symbol conversion at preprocess time (`#119`'s remaining work).
- GENCODE clone resolution (`#139`, deferred — needs GTF data source).
- Removing `manually_added=1` stubs from `central_gene` for "junk" categories (e.g. ENSG IDs that already exist as approved symbols) — that's a separate cleanup orthogonal to this redesign.
- Retiring the silent `dropna()` in `hsc-asd-organoid-m5/preprocess.py` (still present; tracked under "retire silent preprocess.py row-drops" in §6).
- Filing the follow-up tickets enumerated in §6.

## 9. Implementation log — deltas vs. the original design

This section captures decisions made during implementation that diverge from §§1–8 above.

### 9.1 Single combined change, no deprecation path

Original §3.5 called for a staged rollout: a library + schema PR with `ignore_missing` deprecated-but-still-parsed, then nine per-dataset migration PRs. **Final shape: one combined working-tree change with hard errors on retired keys.** Reason: the user pointed out that `ignore_missing` was introduced recently and every caller is in this repo, so a deprecation window costs more than it buys. `GeneMapping.from_json` now raises `ValueError` if it sees `ignore_missing`, `replace`, or `to_upper`, with a message naming the new home for each.

### 9.2 manual_aliases is strict; trailing-dot fix uses pandas

Original §3.3 said the manual_aliases target "resolves through the normalizer (so `NOV → CCN3` only succeeds if `CCN3` is a current approved symbol — guards against typos)." The implementation makes this **a hard `ValueError`** rather than a silent fail, which has a knock-on consequence: the dynamic_convergence trailing-dot fix (`ABALON. → ABALON`, `SGK494. → SGK494`) cannot use manual_aliases because `ABALON` and `SGK494` are themselves retired-no-successor symbols (handled via `record_values:`). The implementation switched to a pandas op (`df["MarkerName"].str.rstrip(".")`) before calling `clean_gene_column`. The original §3.4 listed manual_aliases as the migration target for these — that was wrong; the plan now reflects the pandas approach.

### 9.3 MPP6 / LOR / DEC1 → record_values, not manual_aliases

§4 listed these under "retired-with-known-successor" but flagged them as needing wrangler/domain-expert review. The implementation puts them in `record_values:` across every affected dataset (brain_organoid_atlas, hsc-asd-organoid-m5, polygenic-risk-20, psychscreen). Promoting them to manual_aliases is a follow-up that requires picking a successor per paper context. `C18orf21` is in the same boat (ambiguous prev-symbol → RMP24 / RMP24P1) and went to `record_values:`.

### 9.4 Empty `ignore_missing: []` knobs were dropped, not migrated

Several datasets had `ignore_missing: []` no-op entries. Rather than translate them to empty `non_resolving:` blocks (also no-ops), the migration drops the line entirely. This includes `sfari` (3 tables), `mgi_phenotypes`, `dynamic_convergence` (Perturbed_Baseline_behavior_pvalues), `brain_organoid_atlas` (S11), `zebraAsd` (RestWake_VisStart_byGene).

### 9.5 `<col>_raw` collision raises

The cleaner now raises `KeyError` if `<col>_raw` already exists in the input frame. This wasn't called out in §3.3, but it matters because hsc-asd-organoid-m5's preprocess.py renames `hgnc_symbol → target_gene` AFTER cleaning; the implementation also renames `hgnc_symbol_raw → target_gene_raw` to keep them in lockstep.

### 9.6 Test directory naming

New tests for `GeneMapping` / `NonResolving` live at [processing/tests/processing_types/](processing/tests/processing_types/). The natural name `tests/types/` shadows the `types` stdlib module during pytest collection on this Python version, hence the rename.

### 9.7 zebraAsd preprocess approach

§3.4 suggested `manual_aliases={"SCN1LAB": "SCN1A"}` for the zebrafish ortholog rename. The actual implementation uses a custom `transform_sample()` because the column being transformed is `Mutant_Experiment_Sample` (a composite like `chd8_HOM_3` from which load-db's `split_column_map` later extracts the gene token); upper-casing + ortholog substitution both have to happen on the source column before that split. `manual_aliases` would have run too late.

### 9.8 brain_organoid_atlas patient_list

§3.1's "drop_values for clinical placeholders" applies to the patient_list table's `Pathologic causative mutation` column. The original preprocess.py routed that file through `clean_gene_column` for symmetry; the implementation switched to a `shutil.copyfile` since the cleaner has nothing useful to do on placeholder strings, and the YAML's `non_resolving.drop_values:` handles them at load-db time.
