# extract significant target-gene pairs from LFC and qval matrices
import gzip


def main() -> None:
    lfc_headers: list[str] | None = None
    lfcs: dict[str, list[str]] = {}
    for line in gzip.open("effects_astrocytes_LFCs.csv.gz", "rt"):
        lfc_row: list[str] = line.rstrip("\r\n").split(",")
        if lfc_headers is None:
            lfc_headers = lfc_row
        else:
            gene: str = lfc_row[0]
            gene_lfcs: list[str] = lfc_row[1:]
            lfcs[gene] = gene_lfcs

    print("#perturbGene\tgene\tLFC\tqVal")
    headers: list[str] | None = None
    for line in gzip.open("effects_astrocytes_qvals.csv.gz", "rt"):
        q_row: list[str] = line.rstrip("\r\n").split(",")
        if headers is None:
            headers = q_row
            assert headers == lfc_headers
        else:
            gene = q_row[0]
            q_vals: list[float] = [float(x) for x in q_row[1:]]
            for target_gene, q_val, lfc in zip(headers[1:], q_vals, lfcs[gene]):
                if q_val < 0.01:
                    out_row: list[str] = [target_gene, gene, str(lfc), str(q_val)]
                    print("\t".join(out_row))


if __name__ == "__main__":
    main()
