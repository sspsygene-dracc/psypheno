# Gene-name cleanup plan (sspsygene)

> **For a fresh agent:** repo is `/Users/jbirgmei/prog/sspsygene`; issue tracker is `sspsygene-dracc/psypheno` (separate GitHub repo, use `gh` against it). Project context: [CLAUDE.md](CLAUDE.md). Wrangler-facing handoff (parallel doc, more detailed): [wrangler_gene_cleanup.md](wrangler_gene_cleanup.md).
>
> The big architectural rewrite landed and most of the cleanup tickets closed. This doc tracks the remaining dev-side work.

## 1. Done

- **Architecture rewrite** (#121, `15edd3d`): `ignore_missing` / `replace` / `to_upper` retired in favor of `non_resolving:` block (`drop_values` / `drop_patterns` / `record_values` / `record_patterns`) + `clean_gene_column(manual_aliases=...)`. `<col>_raw` preserved. Strict load-db dispatch; link-table asymmetry fixed. All 8 datasets that used the old knobs migrated; new `preprocess.py` for `zebraAsd`. 27 new pytest cases.
- **Helper extensions** (`35a425d`): new `rna_family` non-symbol category (Y_RNA, U-snRNAs, snoRNAs, miRNAs, SRP/7SK/Vault); `_GENCODE_CLONE_RE` extended with `ABC7-`, `EM:`, `yR`, `XX-DJ`, `XX-FW`, `CITF`, `GHc-`, `SC22CB-`, `bP-` prefixes. 42 new test cases. Polygenic-risk-20 Supp_1 unresolved drops 3,781 → 741 once datasets opt in.
- **Tickets closed in this round:** #93, #120, #121, #122, #123, #124, #126 (tracker). Sub-tracker entries in #126 all ticked except deferred #139.
- **Full DB rebuild verified** (2026-04-30): no errors; genuine unknowns dropped from ~6,651 → 75 (~99% reduction). 16,465 newly-visible non-symbol-identifier warnings remain, expected to drop to ~75 once §2.1 lands.

## 2. Still TODO (dev-side)

Nothing — the only dev-side item left was passing `resolve_hgnc_id=True` to the hsc supp3 / supp12 cleaners, which landed alongside this plan revision (commit ref TBD). All remaining cleanup is wrangler-side; see §3.

## 3. Wrangler followups

Tracked in [wrangler_gene_cleanup.md §4](wrangler_gene_cleanup.md) and not blocking dev work. Brief list for context:

- **`record_patterns:` rollout** across 6 datasets. Biggest single remaining win — drops the 16,465 non-symbol-identifier warnings to ~75. Mechanical YAML edits per the policy in wrangler doc §4.5 (`record_patterns:` for contig / gencode_clone / genbank_accession / ensembl_mouse; `drop_patterns:` for rna_family). Per-dataset table is in the wrangler doc.
- §4.1 `MPP6` / `LOR` / `DEC1` / `C18orf21` successor pick per paper context (currently parked in `record_values:`).
- §4.2 polygenic-risk-20 retired-symbol long tail — 51 unique values that need triage into `manual_aliases:` vs `record_values:` (e.g. `AGPAT9 → GPAT3`, `SF3B14 → SF3B6`, `C11orf48 → LBHD1`). Includes 5 suspected-Excel-mangling cases (`DKK 1.00` shape).
- §4.3 sfari `Slc30a3` species mismatch — 1 warning, low priority.
- §4.4 hsc-asd-organoid-m5 silent `dropna()` retire — ~87k rows; needs its own commit + rebuild check due to DB-size impact.
- §4.5 record vs drop policy reference (already decided; documented).

## 4. Future work / out of scope

- **#119**: ENSG → symbol resolution at preprocess time (the future `resolve_via_ensembl_map: bool` flag). Once it lands, `[ensembl_human, ensembl_mouse]` `record_patterns:` entries can become `drop_patterns:` or go away.
- **#139** (deferred): GENCODE clone *resolution* (not just regex matching) — needs an Ensembl GTF data source. Stays open.
- **Junk-stub cleanup in `central_gene`** — datasets pre-rewrite stubbed ENSG IDs that already exist as approved HGNC symbols. Useless duplicates; separate cleanup orthogonal to this plan.
- **Drop-audit TSV / row-count regression test** — emit per-dataset `(input − DB-rows − dropped)` accounting; needs #117's test infra first.

## 5. Verification recipe (when running 2.1 / 2.2)

```bash
sed 's|"db/sspsygene.db"|"db/sspsygene-claude.db"|' \
    processing/src/processing/config.json > /tmp/sspsygene-config-claude.json

SSPSYGENE_DATA_DIR=$(pwd)/data \
SSPSYGENE_CONFIG_JSON=/tmp/sspsygene-config-claude.json \
    processing/.venv-claude/bin/sspsygene load-db 2>&1 | tee /tmp/load.log

grep -c "not in gene maps"                          /tmp/load.log
grep -c "looks like a non-symbol identifier"        /tmp/load.log
grep "looks like a non-symbol identifier" /tmp/load.log \
  | grep -oE "looks like a non-symbol identifier \([^)]+\)" \
  | sort | uniq -c | sort -rn
```

Spot checks:

- `manual_aliases` rescues: `SELECT * FROM central_gene WHERE human_symbol IN ('CCN3','QARS1','PWWP3A','TAFAZZIN','SARS1');` should return canonical HGNC entries (not stubs); `SELECT * FROM central_gene WHERE human_symbol='NOV'` should be zero rows.
- `<col>_raw` present in cleaned TSVs.
- `central_gene` row count diff: each new `record_values` / `record_patterns` entry = +1 stub per unique value; `drop_*` entries = no change.
