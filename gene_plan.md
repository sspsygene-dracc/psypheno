# Gene-name cleanup plan (sspsygene)

> **For a fresh agent:** repo is `/Users/jbirgmei/prog/sspsygene`; issue tracker is `sspsygene-dracc/psypheno` (separate GitHub repo, use `gh` against it). Project context: [CLAUDE.md](CLAUDE.md). Wrangler-facing handoff: [wrangler_gene_cleanup.md](wrangler_gene_cleanup.md). The architectural rewrite already landed; this doc tracks what's left.

## 1. Done

- **Architecture rewrite** (#121, `15edd3d`): `ignore_missing` / `replace` / `to_upper` retired in favor of `non_resolving:` block (`drop_values` / `drop_patterns` / `record_values` / `record_patterns`) + `clean_gene_column(manual_aliases=...)`. `<col>_raw` preserved. Strict load-db dispatch; link-table asymmetry fixed. All 8 datasets that used the old knobs migrated; new `preprocess.py` for `zebraAsd`. 27 new pytest cases.
- **Helper extensions** (`35a425d`): new `rna_family` non-symbol category (Y_RNA, U-snRNAs, snoRNAs, miRNAs, SRP/7SK/Vault); `_GENCODE_CLONE_RE` extended with `ABC7-`, `EM:`, `yR`, `XX-DJ`, `XX-FW`, `CITF`, `GHc-`, `SC22CB-`, `bP-` prefixes. 42 new test cases.
- **`resolve_hgnc_id=True` for hsc cleaner** (`136e0cc`): the 2 raw `HGNC:NNNNN` literals in supp3 now resolve at preprocess time (e.g. `HGNC:18790 → NSG1`).
- **ENSG → symbol resolution moved to preprocess time** (#119, `b1797e9` + `04fcb9c`): new `EnsemblToSymbolMapper` (parses HGNC + Alliance source files directly, decoupled from `central_gene`) plus `clean_gene_column(resolve_via_ensembl_map=True)` flag tagged `rescued_ensembl_map`. Slotted before `is_non_symbol_identifier` so orphan IDs still classify as `non_symbol_ensembl_*`. Migrated four datasets: `hsc-asd-organoid-m5`, `polygenic-risk-20`, `mgi_phenotypes` (new preprocess.py — 38,532 ENSMUSGs resolved in `Marker Ensembl ID`), `sfari` (new preprocess.py for `sfari_human_genes` — 1,225 ENSGs resolved in `ensembl-id`). For mgi/sfari the cleaned column keeps its original name; the auto-generated `_raw` column preserves the actual ID for audit; field labels updated. Deleted [`web/lib/ensembl-symbol-resolver.ts`](web/lib/ensembl-symbol-resolver.ts) and cleaned 5 API call sites. The `ensembl_to_symbol` SQLite table build remains in place (natural artifact for #99). 13 new pytest cases (9 `EnsemblToSymbolMapper`, 4 `clean_gene_column` flag tests); fixtures (`hgnc_stub.txt`, new `alliance_homology_stub.rpt`) populated with verified real values.
- **Tickets closed in this round:** #93, #119, #120, #121, #122, #123, #124, #126 (tracker). All sub-tracker entries ticked except deferred #139.
- **Full DB rebuild verified** (2026-04-30, post-#119): no errors; 0 `ensembl_human` warnings (down from significant — all rescued via the migration); 9 `ensembl_mouse` warnings (orphan ENSMUSGs without symbol mappings — expected). Remaining 16,494 non-symbol warnings break down as `contig` 11,520 / `gencode_clone` 4,931 / `rna_family` 28 / `genbank_accession` 15 — all addressed via the wrangler `record_patterns:` rollout (§2) and the deferred #139.

## 2. Wrangler followups

Tracked in [wrangler_gene_cleanup.md §4](wrangler_gene_cleanup.md), not blocking dev work:

- **`record_patterns:` rollout** across 6 datasets. Biggest single remaining win — drops the 16,465 non-symbol warnings to ~75. Mechanical YAML edits per the policy in wrangler doc §4.5 (`record_patterns:` for contig / gencode_clone / genbank_accession / ensembl_mouse; `drop_patterns:` for rna_family).
- §4.1 `MPP6` / `LOR` / `DEC1` / `C18orf21` successor pick per paper context (currently parked in `record_values:`).
- §4.2 polygenic-risk-20 retired-symbol long tail — 51 unique values that need triage into `manual_aliases:` vs `record_values:`.
- §4.3 sfari `Slc30a3` species mismatch — 1 warning, low priority.
- §4.4 hsc-asd-organoid-m5 silent `dropna()` retire — ~87k rows; needs its own commit + rebuild check due to DB-size impact.

## 3. Open ticket — context for a fresh agent

One ticket (#139) remains open after #119 landed. The implementation pattern is now well-precedented — read the §1 summary of #119 first, then the file pointers below, since #139 mirrors #119's shape (sibling index class + `clean_gene_column` flag).

### 3.1 #139 — Tier C/C4: GENCODE clone resolution via Ensembl annotation parse

**Title:** "Tier C/C4: GENCODE clone resolution via Ensembl annotation parse" — [GitHub link](https://github.com/sspsygene-dracc/psypheno/issues/139).

**The current state.**

GENCODE/HAVANA clone names (`RP11-…`, `CTD-…`, `KB-…`, `LL0XNC01-…`, `XXbac-…`, etc.) are pre-symbol HAVANA names from older GENCODE/Ensembl releases. They appeared in the original #126 baseline as ~5,121 hits (largest single warning category). After the architecture rewrite + helper extensions, they're now silenced via the `gencode_clone` non-symbol category — **silenced, not resolved**. They get a stub in `central_gene` with the clone name as `human_symbol`, no HGNC ID, no Ensembl ID, no homology.

**Why "deferred" was the right answer.**

The HGNC source file does NOT map clone names to ENSG / current symbols. From the ticket body: HGNC alone catches ~296 of 5,121 clones (~6%) via existing `alias_symbol` / `prev_symbol` columns — that's already in [`symbol_index.py`](processing/src/processing/preprocessing/symbol_index.py)'s ambiguity-aware alias map. The remaining 94% need a NEW data source: a GENCODE GTF parse.

**Implementation pattern — mirror #119.** #119 just added [`EnsemblToSymbolMapper`](processing/src/processing/preprocessing/ensembl_index.py) and a `resolve_via_ensembl_map: bool` flag on `clean_gene_column`. This ticket wants the same shape: a sibling index class plus a flag. Use those as your template for file layout, fixture style, and test structure ([`test_ensembl_index.py`](processing/tests/preprocessing/test_ensembl_index.py)).

**Proposed approach** (from the ticket body, lightly updated):

1. **Choose a GENCODE release.** Ticket suggests latest stable (v45) or pinned to v38 to match the polygenic-risk-20 paper era. Decide based on coverage measurement (parse both, see which catches more of the 5,121). Practical: download `gencode.v45.long_noncoding_RNAs.gtf.gz` (~4.5 MB) first since most clone names are lncRNA placeholders; fall back to the basic-annotation GTF (~28 MB) if the lncRNA-only file misses too many.
2. **One-time parse.** Write a script (probably `processing/src/processing/build_gencode_clone_map.py`) that turns the GTF into a small `data/homology/gencode_clone_map.tsv`. Format: `clone_name\tgene_id\tcurrent_status` where `current_status` is one of `current` / `retired` / `replaced_by:NNN`. Check the TSV into the repo (it's small) so wranglers don't need GTFs locally.
3. **Cross-reference `gene_id` (ENSG) against HGNC's `ensembl_gene_id`** column to derive `current_HGNC_symbol` where available. (HGNC parsing already exists in [`ensembl_index.py:_load_hgnc`](processing/src/processing/preprocessing/ensembl_index.py) — copy that pattern rather than reading `central_gene_table.py`'s richer parser.)
4. **Sibling index class.** Add `GencodeCloneIndex` to a new module `processing/src/processing/preprocessing/gencode_clone_index.py`, mirroring `EnsemblToSymbolMapper`'s shape: `@dataclass`, `from_paths()` / `from_env()` constructors, lookup method `resolve_gencode_clone(name) -> tuple[str, str | None]` returning one of:
   - `("hgnc_symbol", current_HGNC_symbol)` — clone has been promoted to a real symbol.
   - `("current_ensg", "ENSG…")` — clone is still a current Ensembl locus, no HGNC symbol assigned. Gives downstream code a stable anchor (callers can then route via `EnsemblToSymbolMapper` if desired, but typically just store the ENSG).
   - `("current_ac_accession", "AC…")` — renamed to a current AC/AL/AP accession.
   - `("retired", None)` — locus no longer exists; falls through to the `gencode_clone` non-symbol category as today.
5. **Wire into `clean_gene_column`.** Add a `resolve_gencode_clone: bool = False` flag and matching `gencode_index: GencodeCloneIndex | None` parameter (mirror the `ensembl_mapper` / `resolve_via_ensembl_map` precedent at [`dataframe.py:46-83`](processing/src/processing/preprocessing/dataframe.py#L46)). Slot the rescue call BEFORE the `is_non_symbol_identifier` classification step — there's an explicit comment marker at [`dataframe.py:163-165`](processing/src/processing/preprocessing/dataframe.py#L163) that's been a TODO for exactly this. Tag rescues `rescued_gencode_clone`. Export the new class from [`preprocessing/__init__.py`](processing/src/processing/preprocessing/__init__.py).
6. **Tests.** Positive case for each of the four `kind` outcomes plus negatives. Use a small fixture TSV (mirror [`alliance_homology_stub.rpt`](processing/tests/preprocessing/fixtures/alliance_homology_stub.rpt)) with verified real clone names. Coverage measurement against `polygenic-risk-20/Supp_1_all.csv` clone list to update tracker numbers if you re-open #126.

**Gotchas:**

- **Don't touch the existing `_GENCODE_CLONE_RE`.** It's a SILENCING mechanism (returns "yes this looks like a clone"). The new helper is a RESOLVING mechanism. They cohabit cleanly: the helper runs first, rescues what it can; values that fall through still match the regex and get classified as `non_symbol_gencode_clone`.
- **GTF parsing.** Use a streaming parser (don't load the whole GTF into memory). The relevant fields are `feature == "gene"` lines, then extract `gene_name` and `gene_id` from the attribute string. There are existing GTF parsers in pip (`gffutils`, `pyranges`) but a small custom parser is also fine — the `attributes` column is just `key "value"; key "value"; …`.
- **Versioning.** Pin the GENCODE release in a config / docstring. If you ever update it, document the diff.

**Out of scope:**

- Per-dataset preprocess.py migrations to pass `resolve_gencode_clone=True` — that's wrangler-side work, mirrors the migration pattern used for `resolve_via_ensembl_map=True` in [hsc-asd-organoid-m5/preprocess.py](data/datasets/hsc-asd-organoid-m5/preprocess.py) and the four other migrated datasets in #119.
- The HGNC-only subset of clone resolution — that's already in #124 (closed).

**Done when:**

- `data/homology/gencode_clone_map.tsv` exists, generated by a checked-in build script.
- `GencodeCloneIndex` exists with unit tests covering all 4 outcomes (mirror [`test_ensembl_index.py`](processing/tests/preprocessing/test_ensembl_index.py)).
- `clean_gene_column(resolve_gencode_clone=True, gencode_index=...)` rescues clones, tagged `rescued_gencode_clone`.
- `npx tsc --noEmit` clean in `web/`; full pytest pass.
- Coverage measurement: rerun preprocess on polygenic-risk-20/Supp_1_all.csv and report how many clones in the original 5,121 set get rescued vs still classified as `non_symbol_gencode_clone`. Expect a substantial dent in the 4,931 `gencode_clone` warnings from the post-#119 rebuild (see §1).

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

- For #139: pre/post comparison of the `gencode_clone` warning count from the breakdown above (post-#119 baseline: 4,931). After running preprocess.py on a dataset with the flag enabled, expect that count to drop and an equivalent number of rows to show resolved symbols / current ENSGs in the cleaned TSV. `<col>_raw` preserves the original clone name.
- `central_gene` row count diff: each new `record_values` / `record_patterns` entry = +1 stub per unique value; `manual_aliases:` rescues = 0 (use existing HGNC entry); `resolve_via_ensembl_map` rescues = 0 (use existing HGNC entry); `resolve_gencode_clone` rescues to a current HGNC symbol = 0 stubs (existing entry); rescues to a current ENSG with no HGNC symbol = +1 stub (analogous to the orphan-ENSG case in #119).
