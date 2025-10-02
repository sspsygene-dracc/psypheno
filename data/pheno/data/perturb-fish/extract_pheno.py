# extract significant target-gene pairs from LFC and qval matrices
import gzip
from typing import Dict, List, Optional


def main() -> None:
    lfcHeaders: Optional[List[str]] = None
    lfcs: Dict[str, List[str]] = {}
    for line in gzip.open("effects_astrocytes_LFCs.csv.gz", "rt"):
        lfcRow: List[str] = line.rstrip("\r\n").split(",")
        if lfcHeaders is None:
            lfcHeaders = lfcRow
        else:
            gene: str = lfcRow[0]
            geneLfcs: List[str] = lfcRow[1:]
            lfcs[gene] = geneLfcs

    print("#perturbGene\tgene\tLFC\tqVal")
    headers: Optional[List[str]] = None
    for line in gzip.open("effects_astrocytes_qvals.csv.gz", "rt"):
        qRow: List[str] = line.rstrip("\r\n").split(",")
        if headers is None:
            headers = qRow
            assert headers == lfcHeaders
        else:
            gene = qRow[0]
            qVals: List[float] = [float(x) for x in qRow[1:]]
            for targetGene, qVal, lfc in zip(headers[1:], qVals, lfcs[gene]):
                if qVal < 0.01:
                    outRow: List[str] = [targetGene, gene, str(lfc), str(qVal)]
                    print("\t".join(outRow))


if __name__ == "__main__":
    main()
