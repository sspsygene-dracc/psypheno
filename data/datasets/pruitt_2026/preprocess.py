"""Preprocess Pruitt et al. 2026 zebrafish baseline behavioral phenotype data.

Source:
  Supplementary Tables 10 and 11 from pruitt_suppl_tables.xlsx.
  Table 10: signed -log10(LMM p-value) for each mutant × behavioral parameter.
    Sign indicates direction of phenotype difference (mutant vs. wild-type).
  Table 11: scaled LMM beta coefficients (effect sizes).
  Pruitt et al. 2026, bioRxiv, doi:10.64898/2026.02.18.706588

  31 zebrafish mutants × 24 behavioral parameters (12 sleep-wake + 12 VSR).
  Linear mixed models (LMM) comparing homozygous mutant vs. wild-type or
  F0 crispant vs. scramble-injected larvae at 5–7 dpf.

Output:
    pruitt_2026_zf_behavior.tsv
"""

import math
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
SOURCE_FILE = DIR / "pruitt_suppl_tables.xlsx"

# Full mutant_id → human HGNC ortholog
MUTANT_TO_HUMAN = {
    "arid1b hom":      "ARID1B",
    "ash1l hom":       "ASH1L",
    "bcl11aab":        "BCL11A",
    "chd8 hom":        "CHD8",
    "kdm5b hom:hom":   "KDM5B",
    "kdm6bab":         "KDM6B",
    "kmt2cab hom:hom": "KMT2C",
    "mbd5":            "MBD5",
    "pogz hom:hom":    "POGZ",
    "ppp2rd5":         "PPP2R5D",
    "setd5":           "SETD5",
    "shank3ab hom:hom":"SHANK3",
    "skiab":           "SKI",
    "slc6a1ab":        "SLC6A1",
    "smarcc2":         "SMARCC2",
    "wacab":           "WAC",
    "ank2ab":          "ANK2",
    "cacna1g hom":     "CACNA1G",
    "cul3 hom:hom":    "CUL3",
    "dyrk1a hom:hom":  "DYRK1A",
    "gria3ab":         "GRIA3",
    "grin2aab hom:hom":"GRIN2A",
    "kmt5b hom":       "KMT5B",
    "nrxn1ab hom:hom": "NRXN1",
    "pten hom:het":    "PTEN",
    "scn1lab hom":     "SCN1A",   # scn1lab is the zebrafish ortholog of human SCN1A
    "chd2":            "CHD2",
    "crebbpab":        "CREBBP",
    "phf12ab":         "PHF12",
    "phf21aab":        "PHF21A",
    "sin3ab":          "SIN3A",
}

# Column header → human-readable behavioral parameter label
BEHAVIOR_LABELS = {
    "RW:avgAct_d":    "Sleep-Wake: Average Daytime Activity",
    "RW:avgAct_n":    "Sleep-Wake: Average Nighttime Activity",
    "RW:avgWak_d":    "Sleep-Wake: Average Daytime Waking Activity",
    "RW:avgWak_n":    "Sleep-Wake: Average Nighttime Waking Activity",
    "RW:slpBout_d":   "Sleep-Wake: Sleep Bouts Day",
    "RW:slpBout_n":   "Sleep-Wake: Sleep Bouts Night",
    "RW:slpLtcy_d":   "Sleep-Wake: Sleep Latency Day",
    "RW:slpLtcy_n":   "Sleep-Wake: Sleep Latency Night",
    "RW:slpLen_d":    "Sleep-Wake: Sleep Length Day",
    "RW:slpLen_n":    "Sleep-Wake: Sleep Length Night",
    "RW:slp_d":       "Sleep-Wake: Daytime Sleep",
    "RW:slp_n":       "Sleep-Wake: Nighttime Sleep",
    "On:mean:STIM":      "VSR-On: Average Response to All Stimuli",
    "On:mean:POST":      "VSR-On: Average Activity after All Stimuli",
    "On:mean:STIM1":     "VSR-On: Average Response to Stimulus #1",
    "On:mean:POST1":     "VSR-On: Average Activity after Stimulus #1",
    "On:mean:STIM-POST": "VSR-On: Stimulus vs. Post-Stimulus Difference",
    "On:mean:STIM5":     "VSR-On: Average Response to Stimulus #5",
    "Off:mean:STIM":     "VSR-Off: Average Response to All Stimuli",
    "Off:mean:POST":     "VSR-Off: Average Activity after All Stimuli",
    "Off:mean:STIM1":    "VSR-Off: Average Response to Stimulus #1",
    "Off:mean:POST1":    "VSR-Off: Average Activity after Stimulus #1",
    "Off:mean:STIM-POST":"VSR-Off: Stimulus vs. Post-Stimulus Difference",
    "Off:mean:STIM5":    "VSR-Off: Average Response to Stimulus #5",
}


def read_wide(sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(SOURCE_FILE, sheet_name=sheet_name, index_col=0, header=0)
    df.index.name = "mutant_id"
    return df


def main() -> None:
    score_df = read_wide("Table 10_zf_baseline_pval")   # signed -log10(p)
    beta_df  = read_wide("Table 11_zf_baseline_betas")  # scaled beta

    # Melt wide → long
    score_long = score_df.reset_index().melt(
        id_vars="mutant_id", var_name="param_key", value_name="signed_log10_pval"
    )
    beta_long = beta_df.reset_index().melt(
        id_vars="mutant_id", var_name="param_key", value_name="beta"
    )

    out = score_long.merge(beta_long, on=["mutant_id", "param_key"])

    # Map to human-readable behavioral parameter label
    out["behavioral_parameter"] = out["param_key"].map(BEHAVIOR_LABELS)

    # Parse zebrafish gene (first token before space, or full string if no space)
    out["zebrafish_gene"] = out["mutant_id"].str.split().str[0]

    # Map to human ortholog
    out["human_gene"] = out["mutant_id"].map(MUTANT_TO_HUMAN)

    # Derive p-value from |signed_log10_pval| (sign encodes direction via beta)
    out["pval"] = out["signed_log10_pval"].abs().apply(lambda x: 10 ** (-x))

    out = out[[
        "human_gene", "zebrafish_gene", "mutant_id",
        "behavioral_parameter", "pval", "beta",
    ]]
    out = out.sort_values(["human_gene", "behavioral_parameter"]).reset_index(drop=True)

    out_path = DIR / "pruitt_2026_zf_behavior.tsv"
    out.to_csv(out_path, sep="\t", index=False)
    print(f"Wrote {len(out)} rows to {out_path.name}")
    print(f"  {out['human_gene'].nunique()} human genes")
    print(f"  {out['behavioral_parameter'].nunique()} behavioral parameters")


if __name__ == "__main__":
    main()
