#! /bin/zsh

wget 'https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt'
wget 'https://www.informatics.jax.org/downloads/reports/HGNC_AllianceHomology.rpt'
wget 'https://zfin.org/downloads/human_orthos.txt'
wget 'https://www.informatics.jax.org/downloads/reports/MGI_EntrezGene.rpt'
wget 'https://humantfs.ccbr.utoronto.ca/download/v_1.01/DatabaseExtract_v_1.01.csv'

# GENCODE v38 GTFs feed processing.build_gencode_clone_map (#139), which
# turns legacy clone identifiers (RP11-, CTD-, KB-, ...) into HGNC symbols
# / stable ENSG anchors / current AC accessions. v38 is pinned because
# most legacy clone names were dropped or renamed in later releases; v38
# still carries them as `gene_name`. Output: gencode_clone_map.tsv
# (committed).
wget 'https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_38/gencode.v38.long_noncoding_RNAs.gtf.gz'
wget 'https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_38/gencode.v38.basic.annotation.gtf.gz'

SSPSYGENE_DATA_DIR="$(cd ../.. && pwd)/data" \
PYTHONPATH=../../processing/src \
    ../../processing/.venv-claude/bin/python \
    -m processing.build_gencode_clone_map
