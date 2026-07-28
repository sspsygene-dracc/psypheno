#! /usr/bin/env python3

# Flatten the astrocyte LFC and q-value matrices into one long
# (perturbation x measured gene) table.
#
# Axis orientation (verified against the raw files): the CSVs are
# measured-gene rows x perturbation columns. The column header carries the
# 127 CRISPRi perturbations plus the two control guides (Control_NT,
# Control_ST); the row label is one of the 277 measured MERFISH genes.
#
# This script used to emit only pairs with qVal < 0.01. That threshold
# silently deleted every perturbation with no significant target -- 104 of
# the 127 perturbed genes never reached the database at all, so Binan 2025
# contributed 23 perturbed-gene rows to the overview matrix instead of 127,
# and its overlap with the other consortium screens read as ~0. The overview
# matrix has a first-class "assayed but not significant" state, so the full
# grid is what it needs. Emitting everything is 35,456 rows -- small.
import gzip


def read_matrix(path: str) -> tuple[list[str], dict[str, list[str]]]:
    """Return (perturbation column names, measured gene -> row values)."""
    header: list[str] | None = None
    rows: dict[str, list[str]] = {}
    for line in gzip.open(path, "rt"):
        row: list[str] = line.rstrip("\r\n").split(",")
        if header is None:
            header = row[1:]
        else:
            rows[row[0]] = row[1:]
    assert header is not None, f"{path} is empty"
    return header, rows


def main() -> None:
    lfc_perturbations, lfcs = read_matrix("effects_astrocytes_LFCs.csv.gz")
    qval_perturbations, qvals = read_matrix("effects_astrocytes_qvals.csv.gz")
    assert lfc_perturbations == qval_perturbations
    assert lfcs.keys() == qvals.keys()

    print("\t".join(["perturbGene", "gene", "LFC", "qVal"]))
    for measured_gene, gene_qvals in qvals.items():
        gene_lfcs = lfcs[measured_gene]
        for perturb_gene, qval, lfc in zip(
            qval_perturbations, gene_qvals, gene_lfcs
        ):
            print("\t".join([perturb_gene, measured_gene, lfc, qval]))


if __name__ == "__main__":
    main()
