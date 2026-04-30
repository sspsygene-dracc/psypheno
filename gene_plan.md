# Gene-name cleanup plan (sspsygene)

> **For a fresh agent:** the repo is `/Users/jbirgmei/prog/sspsygene`; issue tracker is `sspsygene-dracc/psypheno` (separate GitHub repo, use `gh` against it). Project context: [CLAUDE.md](CLAUDE.md). The big architectural rewrite already landed; this doc tracks the remaining cleanup.

## 1. What's already done

Architecture rewrite landed as `15edd3d` ("Replace ignore_missing with non_resolving + manual_aliases (#121)"). #121 closed; tracker #126 ticked. Summary:

- **`GeneMapping` schema replaced.** `ignore_missing` / `replace` / `to_upper` retired (hard-error on parse). New `non_resolving:` block has four buckets: `drop_values` / `drop_patterns` (orphan link, no stub, no warn) and `record_values` / `record_patterns` (warn-suppressed `manually_added=1` stub + link). `record_patterns` / `drop_patterns` validate against `NON_SYMBOL_CATEGORIES` (= `is_non_symbol_identifier`'s known categories: `ensembl_human`, `ensembl_mouse`, `contig`, `gencode_clone`, `genbank_accession`).
- **Strict load-db dispatch.** Order: `ignore_empty` → `multi_gene_separator` split → species_map → `non_resolving.classify` (drop / record) → fallback warn+stub+link. Implicit Tier B silencing is gone — datasets must opt in via `record_patterns:`.
- **`clean_gene_column` API additions.** Preserves the original value in `<col>_raw` (raises `KeyError` on collision). New `manual_aliases: dict[str, str]` parameter for retired-with-known-successor symbols (raises `ValueError` if the target doesn't resolve through the normalizer — guard against typos).
- **Link-table asymmetry bug fixed.** First-encounter row of a previously-unseen unresolved symbol no longer orphaned.
- **Per-dataset migrations.** All 8 datasets that used `ignore_missing` migrated; new `preprocess.py` for `zebraAsd`. `manual_aliases` applied for the 5 high-confidence cases (`NOV→CCN3`, `QARS→QARS1`, `MUM1→PWWP3A`, `TAZ→TAFAZZIN`, `SARS→SARS1`) per NDD-paper context. `MPP6 / LOR / DEC1 / C18orf21` parked in `record_values:` pending domain-expert review.
- **Tests.** 27 new pytest cases; 139/139 pass.

Full DB rebuild (2026-04-30, against the live DB by user choice) succeeded with no errors. Stats:

- **75 genuine "not in gene maps" warnings** (down from ~6,651 in #126's baseline — ~99% reduction).
- **16,465 "non-symbol identifier" warnings** — *new* noise from the implicit Tier B silencing being removed; tractable per-dataset (see §3).

## 2. Remaining policy still owed by the architecture

The new `non_resolving:` mechanism is in place but most datasets haven't filled out their `record_patterns:` / `drop_patterns:` yet. That's the work below.

For the categories that surfaced post-rebuild:

- **contigs / GENCODE clones / GenBank accessions** → `record_patterns:` (real measured loci that just lack an HGNC-approved symbol; orphaning loses the join).
- **`ensembl_mouse` for mgi_phenotypes** → `record_patterns:` (will resolve to real symbols once #119's preprocess-time ENSG→symbol lands; until then a stub is correct).
- **RNA-family labels** (`Y_RNA`, `SNOR*`, `MIR*`, `snoU*`, etc.) → these are *family labels*, not specific loci. Stubbing `Y_RNA` to one central_gene row is biologically wrong. Lean toward `drop_patterns:` (a new `rna_family` category — see §3.4).

## 3. Concrete next steps (priority order)

### 3.1 Add `record_patterns:` to silence the 16,465 Tier-B warnings — biggest win, all mechanical

Per-dataset additions:

| Dataset | Mapping(s) | `record_patterns:` |
|---|---|---|
| hsc-asd-organoid-m5 | supp3 `target_gene` | `[contig, gencode_clone, genbank_accession]` |
| polygenic-risk-20 | Supp1 + Supp2 `target_gene` | `[contig, gencode_clone, genbank_accession]` |
| brain_organoid_atlas | NEBULA 0.05 / 0.2 + S10 `gene_symbol` | `[contig, gencode_clone]` |
| dynamic_convergence | `MarkerName` | `[contig, gencode_clone]` |
| psychscreen | all 4 tables `gene` | `[contig, gencode_clone]` |
| mgi_phenotypes | `Marker Ensembl ID` | `[ensembl_mouse]` |
| sfari | `model-symbol` | `[contig, gencode_clone]` (only 1 hit; verify before adding) |

Drops the warning count from 16,540 → ~75. Single-PR-sized.

### 3.2 Pass `resolve_hgnc_id=True` to hsc supp3 cleaner

Two unresolved values in hsc are raw HGNC ID literals (`HGNC:18790`, `HGNC:24955`). The cleaner already supports this; [hsc-asd-organoid-m5/preprocess.py:107-111](data/datasets/hsc-asd-organoid-m5/preprocess.py#L107) just doesn't pass `resolve_hgnc_id=True`. One-line fix; rerun preprocess.

### 3.3 Sfari `Slc30a3` species mismatch

`Slc30a3` is a mouse symbol surfacing in `SFARI-Gene_animal-rescues.csv → model-symbol`, which the YAML maps as `species: human`. Diagnose options:

- The animal-rescue table mixes model organisms per row; `species: human` may be wrong globally.
- Easiest: change the species, or upper-case in preprocess.py and let the human normalizer pick it up via case-insensitive fallback (which works for `SLC30A3`).
- Punt: `record_values: [Slc30a3]` (least correct but single-symbol and stops the warning).

Wrangler call. 1 warning total — low priority compared to §3.1.

### 3.4 Polygenic-risk-20 long tail (72 unique unknowns)

Already analyzed in detail: RNA family labels (Y_RNA, U3, SNORD*, SNORA*, snoU*, MIR*, Metazoa_SRP, Vault — ~21 uniques, ~2,500+ row hits — `Y_RNA` alone is 2,112), GENCODE-clone-shaped names that slipped the regex (~6 + more in "other"), retired/old HGNC names (~13 + 42 in "other"). Three sub-fixes:

1. **Broaden `_GENCODE_CLONE_RE`** in [helpers.py:33-35](processing/src/processing/preprocessing/helpers.py#L33) to include the missing prefixes: `ABC7-`, `EM:`, `yR\d+`, `XX-DJ\d`, `CITF`, `GHc-`, `SC22CB-`, `bP-\d`. Library-only change; helps every dataset; existing `record_patterns: [gencode_clone]` then catches them.
2. **Add new `rna_family` category** to `is_non_symbol_identifier` matching `^(Y_RNA|U\d+|snoU\d+|SNOR[ABCD]\d+|Metazoa_SRP|7SK|Vault|MIR\d.*)$`. Then datasets opt in via `drop_patterns: [rna_family]` (orphan, no stub — the right call since these are family labels, not loci).
3. **Retired symbols** (`OCLM`, `AGPAT9`, `STRA13`, `C20ORF135`, `C11orf48`, `SF3B14`, `ZAR 1.00`, `SGK110`, `SGK196`, `PDPK2`, `MGC20647`, `GGTA1P`, `DKFZP*`, `FLJ*`, `KIAA*`, `FKSG62`, `HDGFRP*`, `UPP2-IT1`, `SNORD53_SNORD92`, `ZHX1-C8ORF76`, …) → split into `manual_aliases:` (where a successor is known: `AGPAT9 → GPAT3`, `SF3B14 → SF3B6`, `C11orf48 → LBHD1`, etc.) vs `record_values:` (no successor). Per-dataset wrangler call; lowest leverage.

Order: do 1 + 2 first (helper changes), then re-run preprocess + load-db to see what's left, then attack the retired-symbol long tail with wrangler input.

### 3.5 Retire the silent `dropna()` in hsc-asd-organoid-m5/preprocess.py

[preprocess.py:104-105](data/datasets/hsc-asd-organoid-m5/preprocess.py#L104) silently throws away ~87,435 rows per supp3 read on `hgnc_symbol` NaN/empty. Per the original §3.2 design, those rows should pass through and let `non_resolving:` decide their fate. Mechanically:

- Remove the dropna + empty-string filter.
- Add `ignore_empty: true` to the `target_gene` mapping in [hsc-asd-organoid-m5/config.yaml](data/datasets/hsc-asd-organoid-m5/config.yaml) so empty values orphan cleanly (already the convention for hsc supp3's `target_gene` and `region_genes` — verify).
- Re-run preprocess + load-db; row count delta confirms ~87k rows are now reachable.

Beware the downstream impact: 87k extra rows in `supplementary_table_3_DE_results.tsv` increases the DB and search results. Worth a separate commit + rebuild check.

### 3.6 Promote `MPP6 / LOR / DEC1 / C18orf21` from `record_values:` to `manual_aliases:`

The plan-section-4 review flagged these as ambiguous. Once a wrangler/domain-expert confirms which prev-symbol to pick (e.g. for NDD context), replace the `record_values:` entries with `manual_aliases:` in the affected `preprocess.py` files. No code change required.

## 4. Verification recipe (for after each step)

Per CLAUDE.md, prefer the side-car DB unless you're explicitly OK rewriting the live one:

```bash
sed 's|"db/sspsygene.db"|"db/sspsygene-claude.db"|' \
    processing/src/processing/config.json > /tmp/sspsygene-config-claude.json

SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=/tmp/sspsygene-config-claude.json \
    processing/.venv-claude/bin/sspsygene load-db 2>&1 | tee /tmp/load.log

grep -c "not in gene maps" /tmp/load.log              # genuine unknowns
grep -c "looks like a non-symbol identifier" /tmp/load.log   # Tier B noise
grep "looks like a non-symbol identifier" /tmp/load.log \
  | grep -oE "looks like a non-symbol identifier \([^)]+\)" \
  | sort | uniq -c | sort -rn   # per-category
```

Key spot checks:

- `manual_aliases` rescues: `sqlite3 data/db/sspsygene-claude.db "SELECT * FROM central_gene WHERE human_symbol IN ('CCN3','QARS1','PWWP3A','TAFAZZIN','SARS1');"` — these should be the canonical HGNC entries (not stubs), and `SELECT * FROM central_gene WHERE human_symbol='NOV'` should return zero rows.
- `<col>_raw` lands in cleaned outputs; spot-check at least one row per resolution tag.
- `central_gene` row count diff vs main: each `record_values` entry = +1 stub; each `manual_aliases` rescue = 0 (uses existing HGNC entry).

## 5. Out of scope / future work

- **#119**: ENSG→symbol resolution at preprocess time (`resolve_via_ensembl_map: bool` flag). Once it lands, the `[ensembl_human, ensembl_mouse]` `record_patterns:` entries can become `drop_patterns:` (or just go away entirely).
- **#139**: GENCODE clone *resolution* (not just regex matching) — needs an Ensembl GTF data source to turn `RP11-783K16.5` into the underlying loci. Deferred.
- **Removing junk `manually_added=1` stubs from `central_gene`** — datasets that pre-rewrite stubbed ENSG IDs that already exist as approved HGNC symbols (a non-zero number, per #119's analysis) leave behind useless duplicate rows. Separate cleanup; orthogonal to this plan.
- **Drop-audit TSV / row-count regression test** — track per-dataset (input − DB-rows − dropped) == 0; emit a `drop_audit.tsv` to `data/db/exports/` and surface on the downloads page. Depends on #117's test infra. Deferred.
