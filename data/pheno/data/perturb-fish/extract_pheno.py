# extract significant target-gene pairs from LFC and qval matrices
import gzip


def main():
    lfcHeaders = None
    lfcs = {}
    for line in gzip.open("effects_astrocytes_LFCs.csv.gz", "rt"):
        row = line.rstrip("\r\n").split(",")
        if lfcHeaders is None:
            lfcHeaders = row
        else:
            gene = row[0]
            geneLfcs = row[1:]
            lfcs[gene] = geneLfcs

    print("#perturbGene\tgene\tLFC\tqVal")
    headers = None
    for line in gzip.open("effects_astrocytes_qvals.csv.gz", "rt"):
        row = line.rstrip("\r\n").split(",")
        if headers is None:
            headers = row
            assert headers == lfcHeaders
        else:
            gene = row[0]
            qVals = [float(x) for x in row[1:]]
            for targetGene, qVal, lfc in zip(headers[1:], qVals, lfcs[gene]):
                if qVal < 0.01:
                    outRow = [targetGene, gene, str(lfc), str(qVal)]
                    print("\t".join(outRow))


if __name__ == "__main__":
    main()
