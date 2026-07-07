"""
Preprocess Fernando et al. 2025 (NRXN1 heterozygous deletion).

Source: Supplementary Tables 2 and 3, Fernando et al. 2025, Nature.
https://doi.org/10.1038/s41586-025-08864-9 (see makeDoc.txt for the
full inventory of supplementary files and why Tables 1, 4, 5, 6, 7
weren't used).

Table 3 (supTabl3.xlsx): genome-wide LeafCutter differential-splicing
results. Ten raw sheets are grouped into two output tables by
experiment type (originally four -- iGLUT/iGABA and shRNA/therapeutic
were each split into separate tables; consolidated after a table-count
review found the split wasn't earning its keep: iGLUT vs. iGABA and
knockdown vs. treatment are just another column each, same as
cell_type/knockdown_type already were within the old shrna_splicing
table):

  - patient_splicing.tsv: NRXN1+/- patient (5'-Del or 3'-Del) vs.
    healthy control, iGLUT + iGABA (`cell_type` + `genotype` columns).
  - isogenic_splicing.tsv: isogenic shRNA knockdown of wildtype (WT-KD)
    or mutant (MT-KD) NRXN1 splice isoforms (recreates the LOF/GOF
    phenotype), plus ASO and beta-estradiol treatment (rescues it),
    iGLUT + iGABA (`cell_type` + `manipulation` columns).

Table 2 (supTabl2.xlsx): nrxn_locus_splicing.tsv. This is the authors'
own NRXN1/NRXN2/NRXN3 candidate-locus highlight table. It exists
because Table 3, despite being described as "genome-wide" in the
paper's SI Guide (Supplementary Information, MOESM1), is missing the
NRXN1 cluster for every comparison EXCEPT the two 3'-Del ones --
verified by grepping the raw supTabl3.xlsx sheets directly (not a bug
in this script) and by reading the authors' own analysis notebook
(github.com/mbfernando/NRXN1, differential_splicing/
7_analayse_differential_splicing.ipynb): its get_sig1()/get_sig23()
functions read the SAME per-experiment
`leafcutter_ds_cluster_significance.txt` file that Table 3 was
presumably exported from, filter to genes containing "NRXN1" (or
"NRXN2"/"NRXN3"), and recompute Bonferroni p.adjust *within that
filtered subset* -- so Table 2's p.adjust is not on the same scale as
Table 3's genome-wide p.adjust for the same cluster (e.g. iGLUT
3'-Del clu_17084_-: 1.09e-19 in Table 2 vs. 3.97e-16 in Table 3).
Table 2 is the only public source for the missing NRXN1 5'-Del /
shRNA-WT-KD / ASO rows -- the underlying full per-cluster files live
only on the authors' private HPC path (per the notebook,
/gpfs/commons/home/atokolyi/...); none of the three GEO accessions in
the Reporting Summary (GSE288880, GSE288881, GSE288964) host
processed splicing output, only raw counts/FASTQ-adjacent files.

Each row (in every output table) is one LeafCutter intron-excision
cluster, not a single gene -- a cluster can span several overlapping
genes. In Table 3, `genes` is LeafCutter's direct exon-junction gene
annotation and is NA for ~5-50% of rows (worse on the small shRNA
sheets); the paper's own `tsg_genes` column is a broader gene-overlap
annotation that is populated in nearly every row where `genes` is NA
(confirmed by inspection: tsg_genes is only also-NA for a handful of
rows dataset-wide). `target_gene` = `genes`, falling back to
`tsg_genes` only when `genes` is missing; `tsg_genes` is kept as its
own column for transparency. (In Table 2, `genes` is always populated
with a single NRXN1/NRXN2/NRXN3 value, so no fallback is needed there.)

target_gene is left as a raw (possibly multi-gene, comma-separated)
string here -- splitting/resolving individual tokens into central_gene
links happens at load-db time via `multi_gene_separator` in
config_DRAFT.yaml, following the `region_genes` precedent in
data/datasets/hsc-autism-organoid-m5/preprocess.py (that column is
also built in plain pandas and never passed through `clean_gene`).
BUT load-db's per-token resolver (GeneMapping.resolve_to_central_gene_table
in processing/src/processing/types/gene_mapping.py) only does a
symbol/alias lookup -- it has no ENSG-to-symbol mapping step the way
`clean_gene(resolve_via_ensembl_map=True)` does for single-value
columns. So raw `ENSG...` tokens (105 of 1521 gene tokens in the 2
Table-3-derived outputs) would otherwise resolve to zero and spawn a
disconnected stub `central_gene` entry literally named "ENSG...".
`_resolve_ensg_tokens()` below fixes that with the same
EnsemblToSymbolMapper `clean_gene` uses, applied per-token before the
comma-join; the pre-fix value is preserved in `target_gene_raw`.

Measured with GeneSymbolNormalizer/EnsemblToSymbolMapper against the
live HGNC/Alliance reference data (see config_DRAFT.yaml note 7 for
the full accounting): of 1521 total gene tokens, 1262 (83.0%) resolve
directly; of the 105 raw ENSG tokens, only 4 have a current mapping
(the rest are GENCODE v92-era IDs for loci retired/unmapped in the
current reference); a further 154 tokens (legacy clone-style symbols
like RP1-283E3.8, plus a couple of true non-gene entries like
Metazoa_SRP) don't resolve either. That ~16.7% won't link to an
existing gene page at load-db time -- it's a real limitation of the
source annotation's vintage (GENCODE v92, ~2019), not something fixable
in preprocessing without a full GENCODE-version cross-reference (out of
scope here); those tokens still get a harmless per-dataset stub entry
rather than an error.

Usage:
    python preprocess.py
"""

import re
from pathlib import Path

import pandas as pd

from processing.preprocessing import EnsemblToSymbolMapper, Pipeline, Tracker

_ENSG_RE = re.compile(r"^ENSG\d+(\.\d+)?$")


def _resolve_ensg_tokens(value: object, mapper: EnsemblToSymbolMapper) -> object:
    """Replace raw ENSG tokens in a comma-separated gene list with their
    approved symbol. Tokens with no current mapping are left as-is."""
    if not isinstance(value, str):
        return value
    resolved = []
    for tok in value.split(","):
        if _ENSG_RE.match(tok):
            sym = mapper.resolve_ensg(tok, species="human")
            resolved.append(sym if sym else tok)
        else:
            resolved.append(tok)
    return ",".join(resolved)


DIR = Path(__file__).resolve().parent
SUPP2 = DIR / "supTabl2.xlsx"
SUPP3 = DIR / "supTabl3.xlsx"

# sheet name -> (output table, extra columns to insert for that sheet)
SHEET_SPECS: dict[str, tuple[str, dict[str, str]]] = {
    # Patient NRXN1+/- deletion vs. control, iGLUT + iGABA.
    "iglut_ctrl_5del": ("patient_splicing.tsv", {"cell_type": "iGLUT", "genotype": "5'-Del"}),
    "iglut_ctrl_3del": ("patient_splicing.tsv", {"cell_type": "iGLUT", "genotype": "3'-Del"}),
    "igaba_ctrl_5del": ("patient_splicing.tsv", {"cell_type": "iGABA", "genotype": "5'-Del"}),
    "igaba_ctrl_3del": ("patient_splicing.tsv", {"cell_type": "iGABA", "genotype": "3'-Del"}),
    # Isogenic manipulations: shRNA knockdown of wildtype or mutant (MT)
    # NRXN1 splice isoforms (recreates the LOF/GOF phenotype), plus ASO
    # and beta-estradiol treatment (rescues it), iGLUT + iGABA.
    "shRNA-WT-KD-iGLUT": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGLUT", "manipulation": "WT-KD shRNA"},
    ),
    "shRNA-WT-KD-iGABA": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGABA", "manipulation": "WT-KD shRNA"},
    ),
    "shRNA-MT-KD-iGLUT": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGLUT", "manipulation": "MT-KD shRNA"},
    ),
    "shRNA-MT-KD-iGABA": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGABA", "manipulation": "MT-KD shRNA"},
    ),
    "Therapy-ASO-iGLUT": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGLUT", "manipulation": "ASO"},
    ),
    "Beta-estradiol": (
        "isogenic_splicing.tsv",
        {"cell_type": "iGLUT", "manipulation": "Beta-estradiol"},
    ),
}

RENAME_COLS = {"p.adjust": "p_adjust"}


def _load_sheet(
    tracker: Tracker,
    table_key: str,
    sheet_name: str,
    ensembl_mapper: EnsemblToSymbolMapper,
) -> pd.DataFrame:
    """Read one supTabl3 sheet, fold tsg_genes into target_gene, and
    resolve any raw ENSG tokens in the result to approved symbols."""
    df = pd.read_excel(SUPP3, sheet_name=sheet_name)
    for col in ("genes", "tsg_genes"):
        df[col] = df[col].astype(str).str.replace(r",\s+", ",", regex=True)
        df.loc[df[col].isin(["NA", "nan"]), col] = pd.NA

    used_fallback = df["genes"].isna() & df["tsg_genes"].notna()
    df["target_gene_raw"] = df["genes"].fillna(df["tsg_genes"])
    df["target_gene"] = df["target_gene_raw"].apply(
        lambda v: _resolve_ensg_tokens(v, ensembl_mapper)
    )
    ensg_fixed = int((df["target_gene"] != df["target_gene_raw"]).fillna(False).sum())
    tracker.record(
        "fill_target_gene_from_tsg_genes",
        table=table_key,
        description=(
            "target_gene_raw = genes, falling back to tsg_genes only where "
            "genes is NA; target_gene = target_gene_raw with raw ENSG "
            "tokens resolved to approved symbols where a current mapping "
            "exists (EnsemblToSymbolMapper)"
        ),
        rows_backfilled=int(used_fallback.sum()),
        rows_with_ensg_resolved=ensg_fixed,
    )
    return df.drop(columns=["genes"])


def _clean_sheet(
    tracker: Tracker,
    out_name: str,
    sheet_name: str,
    extra_cols: dict[str, str],
    ensembl_mapper: EnsemblToSymbolMapper,
) -> pd.DataFrame:
    table_key = f"{out_name}:{sheet_name}"
    raw = _load_sheet(tracker, table_key, sheet_name, ensembl_mapper)

    pipeline = (
        Pipeline(table_key, tracker=tracker)
        .from_dataframe(raw, label=f"supTabl3.xlsx:{sheet_name}")
        .drop_columns("status")
        .rename(RENAME_COLS)
        .insert_column("perturbed_gene", "NRXN1")
    )
    for col, value in extra_cols.items():
        pipeline = pipeline.insert_column(col, value)
    pipeline = pipeline.reorder(
        [
            "cluster",
            "target_gene",
            "target_gene_raw",
            "perturbed_gene",
            *extra_cols.keys(),
            "loglr",
            "df",
            "p",
            "p_adjust",
            "tsg_genes",
        ]
    )
    return pipeline.run()


# supTabl2 sheets to parse for NRXN1/NRXN2/NRXN3 candidate-locus results.
SUPP2_SHEETS = [
    "iGLUT_LC_PatientvControl",
    "iGABA_LC_PatientvControl",
    "shRNA-LC_Results",
    "Theraputics-LC_Results",
]

# Section title (verbatim, column A of supTabl2) -> (comparison label, cell_type)
SUPP2_SECTIONS: dict[str, tuple[str, str]] = {
    "iGLUT Control v. 5'-Del": ("iGLUT 5'-Del vs. control", "iGLUT"),
    "iGLUT Control v. 3'-Del": ("iGLUT 3'-Del vs. control", "iGLUT"),
    "iGABA Control v. 5'-Del": ("iGABA 5'-Del vs. control", "iGABA"),
    "iGABA Control v. 3'-Del": ("iGABA 3'-Del vs. control", "iGABA"),
    "iGLUT WT-KD shRNA": ("iGLUT WT-KD shRNA vs. non-targeting shRNA", "iGLUT"),
    "iGABA WT-KD shRNA": ("iGABA WT-KD shRNA vs. non-targeting shRNA", "iGABA"),
    "iGABA MT-KD shRNA": ("iGABA MT-KD shRNA vs. non-targeting shRNA", "iGABA"),
    "iGLUT MT-KD shRNA": ("iGLUT MT-KD shRNA vs. non-targeting shRNA", "iGLUT"),
    "iGLUT MT-KD ASO (v. non-targeting ASO)": (
        "iGLUT MT-KD ASO vs. non-targeting ASO",
        "iGLUT",
    ),
    "iGLUT Estradiol (v. vehicle)": ("iGLUT beta-estradiol vs. vehicle", "iGLUT"),
}


def _parse_supp2(tracker: Tracker) -> pd.DataFrame:
    """Parse supTabl2's NRXN1/NRXN2/NRXN3 candidate-locus highlight sheets.

    supTabl2 is a hand-formatted export (R console printout pasted into
    Excel): each sheet has several sections (one per experimental
    comparison), each with a "[NRXN1]" and a "[NRXN2/3]" sub-block.
    Section titles, "A data.frame: N x 8" lines, and "Top" vs.
    "Significantly" wording all vary between sections -- the only
    structurally invariant marker is the data header row
    (cluster/status/loglr/.../sig_bonf), so this scans for that row and
    tags whatever data rows follow with the most recently seen section
    title, until a blank row ends the block.
    """
    records: list[dict] = []
    for sheet_name in SUPP2_SHEETS:
        raw = pd.read_excel(SUPP2, sheet_name=sheet_name, header=None)
        section: str | None = None
        i = 0
        n = len(raw)
        while i < n:
            col_a, col_b, col_c = raw.iat[i, 0], raw.iat[i, 1], raw.iat[i, 2]
            if isinstance(col_a, str) and col_a.strip() in SUPP2_SECTIONS:
                section = col_a.strip()
            if (
                isinstance(col_b, str)
                and col_b.strip() == "cluster"
                and isinstance(col_c, str)
                and col_c.strip() == "status"
            ):
                # Data rows start two rows below (skip the <chr>/<dbl>
                # type-annotation row) and run until a blank row.
                j = i + 2
                while j < n and isinstance(raw.iat[j, 1], str):
                    records.append(
                        {
                            "cluster": raw.iat[j, 1],
                            "status": raw.iat[j, 2],
                            "loglr": raw.iat[j, 3],
                            "df": raw.iat[j, 4],
                            "p": raw.iat[j, 5],
                            "p_adjust": raw.iat[j, 6],
                            "target_gene": raw.iat[j, 7],
                            "sig_bonf": bool(raw.iat[j, 8]),
                            "section": section,
                            "sheet": sheet_name,
                        }
                    )
                    j += 1
                i = j
                continue
            i += 1

    df = pd.DataFrame.from_records(records)
    tracker.note_input(SUPP2.name)
    tracker.record(
        "parse_supp2_nrxn_locus",
        table="nrxn_locus_splicing.tsv",
        description=(
            "Hand-parsed supTabl2's NRXN1/NRXN2/NRXN3 candidate-locus "
            "sections (structurally irregular hand-formatted export -- "
            "see module docstring)"
        ),
        rows_parsed=len(df),
        unmatched_sections=sorted(
            set(df["section"].tolist()) - set(SUPP2_SECTIONS)
        ),
    )

    df = df[df["status"] == "Success"].drop(columns=["status"])
    unknown = df.loc[~df["section"].isin(SUPP2_SECTIONS), "section"].unique()
    if len(unknown):
        raise ValueError(f"supTabl2: unrecognized section title(s): {unknown!r}")

    df["comparison"] = df["section"].map(lambda s: SUPP2_SECTIONS[s][0])
    df["cell_type"] = df["section"].map(lambda s: SUPP2_SECTIONS[s][1])
    df["perturbed_gene"] = "NRXN1"
    df = df.drop(columns=["section", "sheet"])
    df = df[
        [
            "cluster",
            "target_gene",
            "perturbed_gene",
            "cell_type",
            "comparison",
            "loglr",
            "df",
            "p",
            "p_adjust",
            "sig_bonf",
        ]
    ]
    df["df"] = df["df"].astype("Int64")
    return df.reset_index(drop=True)


def main() -> None:
    tracker = Tracker()
    tracker.note_input(SUPP3.name)
    ensembl_mapper = EnsemblToSymbolMapper.from_env()

    by_output: dict[str, list[str]] = {}
    for sheet_name, (out_name, _extra) in SHEET_SPECS.items():
        by_output.setdefault(out_name, []).append(sheet_name)

    for out_name, sheet_names in by_output.items():
        frames = [
            _clean_sheet(
                tracker, out_name, sheet_name, SHEET_SPECS[sheet_name][1], ensembl_mapper
            )
            for sheet_name in sheet_names
        ]
        combined = pd.concat(frames, ignore_index=True)
        combined["df"] = combined["df"].astype("Int64")

        out_path = DIR / out_name
        combined.to_csv(out_path, sep="\t", index=False)
        tracker.write_concat(
            out_path,
            inputs=[SUPP3.name],
            sheets=sheet_names,
            rows=len(combined),
        )
        print(
            f"Wrote {len(combined)} rows to {out_path.name} "
            f"(sheets: {', '.join(sheet_names)})"
        )

    nrxn_locus = _parse_supp2(tracker)
    out_path = DIR / "nrxn_locus_splicing.tsv"
    nrxn_locus.to_csv(out_path, sep="\t", index=False)
    tracker.write_concat(
        out_path,
        inputs=[SUPP2.name],
        sheets=SUPP2_SHEETS,
        rows=len(nrxn_locus),
    )
    print(f"Wrote {len(nrxn_locus)} rows to {out_path.name} (sheets: {', '.join(SUPP2_SHEETS)})")


if __name__ == "__main__":
    main()
