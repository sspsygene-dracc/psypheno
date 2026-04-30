# Gene-name cleanup plan (sspsygene)

> **For a fresh agent:** repo is `/Users/jbirgmei/prog/sspsygene`; issue tracker is `sspsygene-dracc/psypheno` (separate GitHub repo, use `gh` against it). Project context: [CLAUDE.md](CLAUDE.md). Wrangler-facing handoff: [wrangler_gene_cleanup.md](wrangler_gene_cleanup.md). The architectural rewrite already landed; this doc tracks what's left.

## 1. Done

- **Architecture rewrite** (#121, `15edd3d`): `ignore_missing` / `replace` / `to_upper` retired in favor of `non_resolving:` block (`drop_values` / `drop_patterns` / `record_values` / `record_patterns`) + `clean_gene_column(manual_aliases=...)`. `<col>_raw` preserved. Strict load-db dispatch; link-table asymmetry fixed. All 8 datasets that used the old knobs migrated; new `preprocess.py` for `zebraAsd`. 27 new pytest cases.
- **Helper extensions** (`35a425d`): new `rna_family` non-symbol category (Y_RNA, U-snRNAs, snoRNAs, miRNAs, SRP/7SK/Vault); `_GENCODE_CLONE_RE` extended with `ABC7-`, `EM:`, `yR`, `XX-DJ`, `XX-FW`, `CITF`, `GHc-`, `SC22CB-`, `bP-` prefixes. 42 new test cases.
- **`resolve_hgnc_id=True` for hsc cleaner** (`136e0cc`): the 2 raw `HGNC:NNNNN` literals in supp3 now resolve at preprocess time (e.g. `HGNC:18790 → NSG1`).
- **Tickets closed in this round:** #93, #120, #121, #122, #123, #124, #126 (tracker). All sub-tracker entries ticked except deferred #139.
- **Full DB rebuild verified** (2026-04-30): no errors; genuine unknowns dropped from ~6,651 → 75 (~99% reduction). 16,465 newly-visible non-symbol-identifier warnings remain — addressed via the wrangler `record_patterns:` rollout (see §2).

## 2. Wrangler followups

Tracked in [wrangler_gene_cleanup.md §4](wrangler_gene_cleanup.md), not blocking dev work:

- **`record_patterns:` rollout** across 6 datasets. Biggest single remaining win — drops the 16,465 non-symbol warnings to ~75. Mechanical YAML edits per the policy in wrangler doc §4.5 (`record_patterns:` for contig / gencode_clone / genbank_accession / ensembl_mouse; `drop_patterns:` for rna_family).
- §4.1 `MPP6` / `LOR` / `DEC1` / `C18orf21` successor pick per paper context (currently parked in `record_values:`).
- §4.2 polygenic-risk-20 retired-symbol long tail — 51 unique values that need triage into `manual_aliases:` vs `record_values:`.
- §4.3 sfari `Slc30a3` species mismatch — 1 warning, low priority.
- §4.4 hsc-asd-organoid-m5 silent `dropna()` retire — ~87k rows; needs its own commit + rebuild check due to DB-size impact.

## 3. Open tickets — context for a fresh agent

Two tickets remain open and are mostly independent. **Suggested order: #119 first (biggest single win), then #139.** (#118 was closed as superseded by #119 — see the closure comment for the rationale; if #119 stalls and the displayed-vs-stored ENSG filter mismatch actually hurts users, reopen #118.)

### 3.1 #119 — Convert ENSG → HGNC at preprocess time, drop runtime resolver

**Title:** "Convert ENSG → HGNC at preprocessing time, drop runtime resolver" — [GitHub link](https://github.com/sspsygene-dracc/psypheno/issues/119).

**The current state of the world.**

Some datasets store raw `ENSG…` IDs in their gene columns (most prominent example: `hsc-asd-organoid-m5/supplementary_table_3_DE_results.tsv` → `target_gene` column). At load-db time the IDs go into the per-dataset SQLite table verbatim. The web app has a runtime rewrite layer that swaps ENSG IDs to symbols on the way out:

- [`web/lib/ensembl-symbol-resolver.ts`](web/lib/ensembl-symbol-resolver.ts) — the resolver. Reads from the `ensembl_to_symbol` SQLite table.
- [`processing/src/processing/ensembl_symbol_table.py`](processing/src/processing/ensembl_symbol_table.py) — builds `ensembl_to_symbol` from `central_gene` entries that have both an Ensembl ID and a symbol.
- The resolver is called from every API route that returns dataset rows: [`web/pages/api/gene-data.ts`](web/pages/api/gene-data.ts), [`significant-rows.ts`](web/pages/api/significant-rows.ts), [`gene-table-page.ts`](web/pages/api/gene-table-page.ts), [`dataset-data.ts`](web/pages/api/dataset-data.ts), [`gene-pair-data.ts`](web/pages/api/gene-pair-data.ts), [`dataset-significant-rows.ts`](web/pages/api/dataset-significant-rows.ts).
- The resolver is keyed by DB inode (handles atomic-rename DB swaps after `load-db` rebuilds).

**Why it's a problem.**

1. SQL operates on the raw stored value, not the displayed symbol. Sort / WHERE / LIKE filters miss for ENSG-storing columns. (#118 — a SQL workaround that bolted a sub-select onto the filter — was closed as superseded by this ticket.)
2. Cache management exists only because the rewrite happens at request time.
3. Every new API route has to remember to call `resolveEnsgsInRows` — easy to miss; downloads (#83) and any future export will need it too.

**Proposed approach** (from the ticket body, lightly updated for current code state):

1. **Audit which datasets store ENSG in gene columns.** Quick way:
   ```bash
   sqlite3 data/db/sspsygene.db \
     "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%__%' AND name != 'central_gene' AND name != 'extra_gene_synonyms' AND name != 'extra_mouse_symbols' AND name != 'data_tables' AND name != 'ensembl_to_symbol';" \
     | while read t; do
         cnt=$(sqlite3 data/db/sspsygene.db "SELECT COUNT(*) FROM (SELECT * FROM \"$t\" LIMIT 1000) WHERE 0"); :
         echo "$t"
         sqlite3 data/db/sspsygene.db "SELECT 'ensg_in:'||name FROM pragma_table_info('$t') WHERE name LIKE '%gene%' OR name LIKE '%symbol%';"
       done
   ```
   Or simpler: `grep` the `<col>_resolution` outputs from the most recent preprocess runs for the `non_symbol_ensembl_human` tag. From the 2026-04-30 rebuild: hsc-asd-organoid-m5/supp3 dominates (~6,084 of the 16,465 Tier-B warnings; most of those are ENSGs). polygenic-risk-20 has some too. mgi_phenotypes has 9 ENSMUSG hits.
2. **Build an `EnsemblToSymbolMapper` available at preprocess time.** Today the mapping `ENSG ↔ symbol` is built INSIDE load-db from `central_gene` (which is itself built from data + Alliance/HGNC sources). To make it available at preprocess time, the new mapper needs to consume the upstream Alliance/HGNC files DIRECTLY, decoupled from `central_gene` construction.
   - HGNC source: `data/homology/hgnc_complete_set.txt` — has `ensembl_gene_id` column (already parsed in [`processing/src/processing/central_gene_table.py:214-258`](processing/src/processing/central_gene_table.py#L214) as `parse_hgnc`).
   - Alliance homology: `data/homology/...` (Alliance file) — for cross-species and ENSMUSG ↔ symbol via the MGI bridge.
   - Recommended location: a new module `processing/src/processing/preprocessing/ensembl_index.py` that mirrors `symbol_index.py`'s shape (a dataclass with `from_paths` / `from_env`, lookup methods).
3. **Wire into `clean_gene_column`** as a new `resolve_via_ensembl_map: bool` flag. Slot it BEFORE `is_non_symbol_identifier` (same ordering invariant as the other rescues) so that ENSG IDs that DO map to symbols get rescued, and only the orphan ENSGs fall through to the non-symbol classifier.
4. **Update affected per-dataset preprocess.py to pass the flag.** `<col>_raw` already preserves the original ENSG (added under #121).
5. **Drop the runtime resolver.** Once the stored value IS the symbol, `web/lib/ensembl-symbol-resolver.ts` and its call sites can be removed. The `ensembl_to_symbol` SQLite table can stay (it's the natural artifact for #99, the downloadable map; just no longer on the request path).
6. **Per-column filter consistency** — once the stored value is the symbol, the existing `LIKE` filter on per-dataset table columns just works without a cross-table join. No web-side change required for filtering; the runtime resolver removal in step 5 already handles the rendering side.

**Gotchas:**

- The `central_gene` table joins via `(human_symbol, mouse_symbols)` in load-db. If a dataset's gene column changes from `ENSG…` to a symbol, the existing load-db `gene_mapping.resolve_to_central_gene_table` will pick it up automatically (it does symbol lookup, not ENSG lookup). No load-db schema change required — preprocess emits symbols, load-db consumes them via the existing path.
- Where there is no symbol mapping, KEEP the raw ENSG. That's an irreducible case; `non_resolving.record_patterns: [ensembl_human]` (or `drop_patterns:`) still applies.
- `<col>_raw` will still hold the ENSG, so you don't lose audit trail.

**Done when:**

- New `EnsemblToSymbolMapper` exists in `processing/src/processing/preprocessing/`, with unit tests using fixture data.
- `clean_gene_column(resolve_via_ensembl_map=True)` rescues ENSG IDs that have known symbols (tagged `rescued_ensembl_map` in `_<col>_resolution`).
- At least 2 datasets migrated (likely hsc-asd-organoid-m5 and mgi_phenotypes since they're the heaviest ENSG-storers).
- `web/lib/ensembl-symbol-resolver.ts` deleted; all 6 API route call sites cleaned up.
- `npx tsc --noEmit` clean in `web/`; full pytest pass.
- Manual smoke test in the dev server: search for a gene that previously came from an ENSG row, click through, confirm the symbol appears.

---

### 3.2 #139 — Tier C/C4: GENCODE clone resolution via Ensembl annotation parse

**Title:** "Tier C/C4: GENCODE clone resolution via Ensembl annotation parse" — [GitHub link](https://github.com/sspsygene-dracc/psypheno/issues/139).

**The current state.**

GENCODE/HAVANA clone names (`RP11-…`, `CTD-…`, `KB-…`, `LL0XNC01-…`, `XXbac-…`, etc.) are pre-symbol HAVANA names from older GENCODE/Ensembl releases. They appeared in the original #126 baseline as ~5,121 hits (largest single warning category). After the architecture rewrite + helper extensions, they're now silenced via the `gencode_clone` non-symbol category — **silenced, not resolved**. They get a stub in `central_gene` with the clone name as `human_symbol`, no HGNC ID, no Ensembl ID, no homology.

**Why "deferred" is currently the right answer.**

The HGNC source file does NOT map clone names to ENSG / current symbols. From the ticket body: HGNC alone catches ~296 of 5,121 clones (~6%) via existing `alias_symbol` / `prev_symbol` columns — that's already in [`symbol_index.py`](processing/src/processing/preprocessing/symbol_index.py)'s ambiguity-aware alias map. The remaining 94% need a NEW data source: a GENCODE GTF parse.

**Proposed approach** (from the ticket body):

1. **Choose a GENCODE release.** Ticket suggests latest stable (v45) or pinned to v38 to match the polygenic-risk-20 paper era. Decide based on coverage measurement (parse both, see which catches more of the 5,121). Practical: download `gencode.v45.long_noncoding_RNAs.gtf.gz` (~4.5 MB) first since most clone names are lncRNA placeholders; fall back to the basic-annotation GTF (~28 MB) if the lncRNA-only file misses too many.
2. **One-time parse.** Write a script (probably `processing/src/processing/build_gencode_clone_map.py`) that turns the GTF into a small `data/homology/gencode_clone_map.tsv`. Format: `clone_name\tgene_id\tcurrent_status` where `current_status` is one of `current` / `retired` / `replaced_by:NNN`. Check the TSV into the repo (it's small) so wranglers don't need GTFs locally.
3. **Cross-reference `gene_id` (ENSG) against HGNC's `ensembl_gene_id`** column to derive `current_HGNC_symbol` where available.
4. **Helper.** Add `resolve_gencode_clone(name) -> tuple[str, str | None]` to [`processing/src/processing/preprocessing/helpers.py`](processing/src/processing/preprocessing/helpers.py) returning one of:
   - `("hgnc_symbol", current_HGNC_symbol)` — clone has been promoted to a real symbol.
   - `("current_ensg", "ENSG…")` — clone is still a current Ensembl locus, no HGNC symbol assigned. Gives #119's pipeline a stable anchor.
   - `("current_ac_accession", "AC…")` — renamed to a current AC/AL/AP accession.
   - `("retired", None)` — locus no longer exists; falls through to the `gencode_clone` non-symbol category as today.
   - Loaded via a sibling class to `GeneSymbolNormalizer` (e.g. `GencodeCloneIndex`) with `from_paths` / `from_env` constructors.
5. **Wire into `clean_gene_column`.** Add a `resolve_gencode_clone: bool = False` flag. Slot it BEFORE `is_non_symbol_identifier` (the existing comment in [`dataframe.py:163-165`](processing/src/processing/preprocessing/dataframe.py#L163) about ordering applies — it's been a TODO marker for exactly this).
6. **Tests.** Positive case for each of the four `kind` outcomes plus negatives. Coverage measurement against `polygenic-risk-20/Supp_1_all.csv` clone list to update tracker numbers if you re-open #126.

**Gotchas:**

- **Don't touch the existing `_GENCODE_CLONE_RE`.** It's a SILENCING mechanism (returns "yes this looks like a clone"). The new helper is a RESOLVING mechanism. They cohabit cleanly: the helper runs first, rescues what it can; values that fall through still match the regex and get classified as `non_symbol_gencode_clone`.
- **GTF parsing.** Use a streaming parser (don't load the whole GTF into memory). The relevant fields are `feature == "gene"` lines, then extract `gene_name` and `gene_id` from the attribute string. There are existing GTF parsers in pip (`gffutils`, `pyranges`) but a small custom parser is also fine — the `attributes` column is just `key "value"; key "value"; …`.
- **Versioning.** Pin the GENCODE release in a config / docstring. If you ever update it, document the diff.

**Out of scope:**

- Per-dataset preprocess.py migrations to pass `resolve_gencode_clone=True` — that's wrangler-side work, mirrors the migration pattern from #142 / #143 / etc.
- The HGNC-only subset of clone resolution — that's already in #124 (closed).

**Done when:**

- `data/homology/gencode_clone_map.tsv` exists, generated by a checked-in build script.
- `resolve_gencode_clone` helper exists with unit tests covering all 4 outcomes.
- Coverage measurement: rerun preprocess on polygenic-risk-20/Supp_1_all.csv and report how many clones in the original 5,121 set get rescued vs still classified as `non_symbol_gencode_clone`.

---

## 4. Verification recipe (for any of the above)

Per CLAUDE.md, prefer the side-car DB unless explicitly OK rewriting the live one:

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

- For #119: `SELECT * FROM hsc_asd_organoid_m5_DE_results LIMIT 5;` — `target_gene` column should hold symbols, not ENSGs (where a mapping exists).
- For #139: `SELECT clone_name, current_HGNC_symbol FROM <new gencode_clone table or temp join>` — reproduce the #126 5,121 figure, see how many got rescued.
- `<col>_raw` present in cleaned TSVs throughout.
- `central_gene` row count diff: each new `record_values` / `record_patterns` entry = +1 stub per unique value; `manual_aliases:` rescues = 0 (use existing HGNC entry); `resolve_via_ensembl_map` rescues = 0 (use existing HGNC entry).
