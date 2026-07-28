# SSPsyGene gene list — provenance and notes

Sidecar for `sspsygene_genes.txt` (259 genes) and `sspsygene_capstone_genes.txt`
(10 genes).

## Source

The consortium's live Google Sheet **"Gene preference selection"**, linked from
the CCC monthly-meeting notes doc as the *"Gene Selection site"*.

Snapshot taken **2026-07-28**. The rest of that sheet is a per-(ADGC × assay ×
cell line) status matrix, a weighted score block, and a mostly-empty Cell Line
KO RRID tab; none of that is mirrored here.

## What the two files contain

| File | Contents |
| --- | --- |
| `sspsygene_genes.txt` | All 259: 250 original (alphabetical) then 9 later additions in sheet order |
| `sspsygene_capstone_genes.txt` | The 10 capstone genes, a subset of the above |

The 250/+9 split is structural, not cosmetic — column A breaks alphabetical
order at exactly index 250, and the 9 trailing entries are styled differently in
the sheet (green font). That independently confirms the header's "(+9 genes)"
and is a useful check that a re-pull wasn't truncated.

## Deviation from the source: SUV420H1 → KMT5B

**This is the one place the committed list intentionally differs from the sheet.**

The sheet carries the legacy symbol `SUV420H1`. The current HGNC symbol is
`KMT5B` (HGNC:24283, Entrez 51111); our `central_gene` table stores `KMT5B` with
`SUV420H1` as a synonym, and has no `SUV420H1` row. `KMT5B` is not separately
present in the sheet, so this is a rename, not a merge.

We substitute `KMT5B` and re-sort, so it sits between `KMT2E` and `LONP1` rather
than in the S's where the sheet has it. With this substitution **all 259 symbols
resolve directly against `central_gene.human_symbol`** — no synonym pass needed.

If you re-pull the sheet, redo this substitution or the join silently drops a
consortium gene. Ideally, ask the wranglers to update the sheet upstream.

Elsewhere the consortium writes this gene as `KMT5B|SUV420H1` (e.g. the Scripps
16-gene in-vivo perturb multiome row in the L3/L4 tracking sheet), so the two
names are known to co-refer within the project.

## How the capstone genes were identified

Capstone genes are marked in the sheet **by red cell fill** (`#F4CCCC`) on
column A — the header's "Capstone genes in red". This does **not** survive CSV
export, so the list was recovered by exporting the sheet as `.xlsx` and reading
fill colours with `openpyxl`. Exactly 10 cells carry that fill.

The resulting set — ARID1B, ASXL3, CACNA1G, CHD8, DLL1, GABRA1, KMT2C, SCN2A,
SHANK3, SMARCC2 — independently matches the Broad 10-gene pilot roster
(`broadNgo_10GenePilot`) and the UCLA scRNA-seq row of the L3/L4 tracking sheet,
which is a good sign the colour reading is right.

Caveat: the `summary tables` tab carries a legend reading *"Capstone Gene's are
highlighted in yellow"*. That refers to that tab's own score block, and in the
current export only legend headers are yellow-filled, no gene cells. Column A's
red fill is the authoritative marking; if the two ever disagree, ask the
wranglers rather than guessing.

## How to refresh

Read the sheet via the Google Drive connector. Note that a plain CSV export
loses the capstone highlighting — use xlsx if you need it:

```python
# download_file_content(fileId=..., exportMimeType=
#   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
import openpyxl
ws = openpyxl.load_workbook("sheet.xlsx")["Spreadsheet"]
genes, capstone = [], []
for r in range(4, ws.max_row + 1):
    c = ws.cell(row=r, column=1)
    if not c.value:
        continue
    genes.append(c.value.strip())
    if c.fill.patternType and c.fill.start_color.rgb == "FFF4CCCC":
        capstone.append(c.value.strip())
core, extra = genes[:250], genes[250:]        # assert 250 / 9 / 10
```

Then apply the `SUV420H1` → `KMT5B` substitution, re-sort `core`, and update the
snapshot date above.

**Drive search will not find this sheet.** `sharedWithMe = true and mimeType =
spreadsheet` returns zero results for it even though it is shared — Google does
not index shared files the user has never opened. Use the link above.

## What this list is for

Per Max in [psypheno#23](https://github.com/sspsygene-dracc/psypheno/issues/23):

> We always add all the genes, not just SSPsyGene genes. We can always filter on
> SSPsyGene genes later in the interface.

So this is a **display/filter** concern — the overview matrix (#220 epic),
"grant-verified" views, a possible "restrict to consortium genes" toggle. Never
filter dataset *ingestion* by it.
