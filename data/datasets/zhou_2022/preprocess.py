"""
Preprocess Zhou et al. 2022 (Nature Genetics) Supplementary Tables S9 + S12.

Table S9: gene-based meta-analysis table (391 autosomal genes selected for
replication in stage 1 + stage 2) -> per-gene TSV of de novo enrichment, TDT,
and case-control burden statistics.

Table S12: per-individual phenotype table (238 patients carrying HC LoFs in
the 5 novel + 5 comparison established ASD risk genes) -> per-patient TSV of
comorbidity flags (cognitive impairment, epilepsy, Tourette, ADHD,
schizophrenia). Same gene can (and does) appear on multiple rows here, one
per patient carrying a variant in it -- that's expected, not a data error.

Paper: Zhou et al. 2022, Nat Genet 54:1305-1319, doi:10.1038/s41588-022-01148-2
Data: Supplementary Tables from the paper's supplementary tables workbook
(see makeDoc.txt)

Usage:
    python preprocess.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

from processing.preprocessing import GeneSymbolNormalizer, Pipeline, Tracker

DIR = Path(__file__).resolve().parent
EXCEL = DIR / "zhou-2022-supplementary-tables.xlsx"

# Columns where "." in the source means "not computed / not applicable" and
# should become a real missing value rather than a literal dot string.
_DOT_AS_NA_COLUMNS = [
    "ExACpLI",
    "Arisk",
    "ForecASD",
    "SFARICategory",
    "SFARIScore",
    "DDDCategory",
    "DDDAllelic",
    "DDDMutCons",
    "pAllEnrichMeta",
    "pMisCombMeta",
    "pTDT",
    "p-value for comparing high-confidence LoF rate among cases and controls (one side binominal test)",
    "Combined p-value from TDT and case-control",
    "Combined p-value from TDT, case-control and DNVs",
    "p-value for comparing high-confidence LoF rate among cases and controls (one side binominal test).1",
    "Combined p-value from TDT and case-control.1",
    "Combined p-value from TDT, case-control and DNVs.1",
    "Maximum combined p-value of TDT, case-control VS gnomADexomeNonNeuro and VS TopMed",
    "Maximum combined p-value of DNVs, TDT, case-control VS gnomADexomeNonNeuro and VS TopMed",
]

# TDTStat uses -999 as a sentinel for "not computed" (paired with pTDT == ".").
_SENTINEL_AS_NA = {"TDTStat": -999}

_RENAME = {
    "Known": "known_asd_ndd_gene",
    "Ascertainment": "ascertainment",
    "GeneID": "ensembl_gene_id",
    "HGNC": "gene",
    "EntrezID": "entrez_id",
    "CytoBand": "cytoband",
    "ExACpLI": "exac_pli",
    "LOEUFbin": "loeuf_decile",
    "Arisk": "a_risk_score",
    "ForecASD": "forecasd_score",
    "ASDdnSignif": "asd_denovo_signif",
    "SFARICategory": "sfari_category",
    "SFARIScore": "sfari_score",
    "DDDCategory": "ddd_category",
    "DDDAllelic": "ddd_allelic_requirement",
    "DDDMutCons": "ddd_mutation_consequence",
    "DDDOrgan": "ddd_organ_specificity",
    "dnLoFCase": "dn_lof_case_count",
    "dnLoFMegaCase": "dn_lof_megaanalysis_case_count",
    "MuLoF": "lof_mutation_rate",
    "dnDmisCase": "dn_dmis_case_count",
    "MuDmis": "dmis_mutation_rate",
    "dnLoFControl": "dn_lof_control_count",
    "dnDmisControl": "dn_dmis_control_count",
    "pAllEnrichMeta": "p_dnv_lof_enrichment_meta",
    "pMisCombMeta": "p_dnv_missense_enrichment_meta",
    "Filter": "hc_lof_filter",
    "Parent": "tdt_informative_parent_count",
    "Trans": "tdt_transmitted_count",
    "NonTrans": "tdt_nontransmitted_count",
    "TransUnaff": "tdt_transmitted_unaffected_count",
    "NonTransUnaff": "tdt_nontransmitted_unaffected_count",
    "TDTStat": "tdt_statistic",
    "pTDT": "p_tdt",
    "Case": "unrelated_case_hc_lof_count",
    "CaseRate": "unrelated_case_hc_lof_rate",
    "EuroCase": "unrelated_case_hc_lof_count_european",
    "EuroCaseRate": "unrelated_case_hc_lof_rate_european",
    "High Confidence LoF count": "hc_lof_case_count_vs_gnomad",
    "High Confidence LoF Rate": "hc_lof_case_rate_vs_gnomad",
    "p-value for comparing high-confidence LoF rate among cases and controls (one side binominal test)": "p_case_control_vs_gnomad",
    "Combined p-value from TDT and case-control": "p_tdt_case_control_vs_gnomad",
    "Combined p-value from TDT, case-control and DNVs": "p_tdt_case_control_dnv_vs_gnomad",
    "High Confidence LoF count.1": "hc_lof_case_count_vs_topmed",
    "High Confidence LoF Rate.1": "hc_lof_case_rate_vs_topmed",
    "p-value for comparing high-confidence LoF rate among cases and controls (one side binominal test).1": "p_case_control_vs_topmed",
    "Combined p-value from TDT and case-control.1": "p_tdt_case_control_vs_topmed",
    "Combined p-value from TDT, case-control and DNVs.1": "p_tdt_case_control_dnv_vs_topmed",
    "gnomADexomeOver15": "coverage_gnomad_exome_over15x",
    "SPARKOver15": "coverage_spark_over15x",
    "gnomADgenomeOver15": "coverage_gnomad_genome_over15x",
    "TopMedOver15": "coverage_topmed_over15x",
    "Maximum combined p-value of TDT, case-control VS gnomADexomeNonNeuro and VS TopMed": "p_max_tdt_case_control",
    "Maximum combined p-value of DNVs, TDT, case-control VS gnomADexomeNonNeuro and VS TopMed": "p_max_combined",
    "Study-wide significance based on 5,754 constraint genes (p<8.69E-06)": "study_wide_significant",
}

_SEX_MAP = {"Female": "Female", "F": "Female", "Male": "Male", "M": "Male"}

_INHERITANCE_MAP = {
    "Maternal": "Maternal",
    "Paternal": "Paternal",
    "Inherited": "Inherited",
    "Unknown": "Unknown",
    "Non Maternal": "Non-maternal",
    "Non Paternal": "Non-paternal",
    "De Novo": "De novo",
    "de novo": "De novo",
}

_PHENOTYPE_FLAG_COLUMNS = [
    "Calculated cognitive impairment",
    "Epilepsy",
    "Tourette syndrome",
    "ADHD",
    "Schizophrenia",
]

_RENAME_S12 = {
    "spid": "sample_id",
    "inheritance": "inheritance",
    "variant_id (hg38)": "variant_id_hg38",
    "gene_symbol": "gene",
    "hgvsc": "hgvsc",
    "hgvsp": "hgvsp",
    "Sex": "sex",
    "Calculated cognitive impairment": "cognitive_impairment",
    "Epilepsy": "epilepsy",
    "Tourette syndrome": "tourette_syndrome",
    "ADHD": "adhd",
    "Schizophrenia": "schizophrenia",
}

# Column order for results.tsv: lead with gene identity + the paper's final
# significance call, so the headline numbers are visible without scrolling
# past all the per-control-set detail columns.
_COLUMN_ORDER = [
    "gene",
    "gene_raw",
    "known_asd_ndd_gene",
    "study_wide_significant",
    "p_max_combined",
    "p_max_tdt_case_control",
    "ascertainment",
    "asd_denovo_signif",
    "ensembl_gene_id",
    "entrez_id",
    "cytoband",
    "exac_pli",
    "loeuf_decile",
    "a_risk_score",
    "forecasd_score",
    "sfari_category",
    "sfari_score",
    "ddd_category",
    "ddd_allelic_requirement",
    "ddd_mutation_consequence",
    "ddd_organ_specificity",
    "dn_lof_case_count",
    "dn_lof_megaanalysis_case_count",
    "lof_mutation_rate",
    "dn_dmis_case_count",
    "dmis_mutation_rate",
    "dn_lof_control_count",
    "dn_dmis_control_count",
    "p_dnv_lof_enrichment_meta",
    "p_dnv_missense_enrichment_meta",
    "hc_lof_filter",
    "tdt_informative_parent_count",
    "tdt_transmitted_count",
    "tdt_nontransmitted_count",
    "tdt_transmitted_unaffected_count",
    "tdt_nontransmitted_unaffected_count",
    "tdt_statistic",
    "p_tdt",
    "unrelated_case_hc_lof_count",
    "unrelated_case_hc_lof_rate",
    "unrelated_case_hc_lof_count_european",
    "unrelated_case_hc_lof_rate_european",
    "hc_lof_case_count_vs_gnomad",
    "hc_lof_case_rate_vs_gnomad",
    "p_case_control_vs_gnomad",
    "p_tdt_case_control_vs_gnomad",
    "p_tdt_case_control_dnv_vs_gnomad",
    "hc_lof_case_count_vs_topmed",
    "hc_lof_case_rate_vs_topmed",
    "p_case_control_vs_topmed",
    "p_tdt_case_control_vs_topmed",
    "p_tdt_case_control_dnv_vs_topmed",
    "coverage_gnomad_exome_over15x",
    "coverage_spark_over15x",
    "coverage_gnomad_genome_over15x",
    "coverage_topmed_over15x",
    "_gene_resolution",
]


def main() -> None:
    tracker = Tracker()
    normalizer = GeneSymbolNormalizer.from_env()

    df = pd.read_excel(EXCEL, sheet_name="Table S9", header=2)
    tracker.note_input(EXCEL.name)

    df[_DOT_AS_NA_COLUMNS] = df[_DOT_AS_NA_COLUMNS].replace(".", np.nan)
    for col, sentinel in _SENTINEL_AS_NA.items():
        df[col] = df[col].replace(sentinel, np.nan)

    # Keep flag columns as human-readable "Yes"/"No" text rather than Python
    # bool: SQLite has no boolean type, so True/False would round-trip as
    # opaque 1/0 by the time they reach the browser.
    df["Known"] = df["Known"].map({"x": "Yes", ".": "No"})  # type: ignore[arg-type]
    df["ASDdnSignif"] = df["ASDdnSignif"].map({"x": "Yes", ".": "No"})  # type: ignore[arg-type]
    # Study-wide significance is already "Yes"/"No" in the source — left as-is.

    df = df.rename(columns=_RENAME)

    (
        Pipeline("results.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(df, label="Table S9")
        .clean_gene("gene", species="human")
        .reorder(_COLUMN_ORDER)
        .write_tsv(DIR / "results.tsv")
        .run()
    )

    df12 = pd.read_excel(EXCEL, sheet_name="Table S12", header=1)
    tracker.note_input(EXCEL.name)

    df12["gene_symbol"] = df12["gene_symbol"].str.strip()
    df12["Sex"] = df12["Sex"].map(_SEX_MAP)  # type: ignore[arg-type]
    df12["inheritance"] = df12["inheritance"].map(_INHERITANCE_MAP)  # type: ignore[arg-type]
    # Keep phenotype flags as "Yes"/"No" text (see note on Table S9 above);
    # unknown/not-collected stays blank rather than "No".
    for col in _PHENOTYPE_FLAG_COLUMNS:
        df12[col] = df12[col].map({1.0: "Yes", 0.0: "No"})  # type: ignore[arg-type]

    df12 = df12.rename(columns=_RENAME_S12)

    (
        Pipeline("results_phenotypes.tsv", tracker=tracker, normalizer=normalizer)
        .from_dataframe(df12, label="Table S12")
        .clean_gene("gene", species="human")
        # gene_raw is identical to gene for all 238 rows here (all 10 gene
        # symbols were already clean HGNC symbols) -- redundant, unlike in
        # zhou_2022_gene_meta where it preserves real pre-resolution values.
        .drop_columns("gene_raw")
        .write_tsv(DIR / "results_phenotypes.tsv")
        .run()
    )


if __name__ == "__main__":
    main()
