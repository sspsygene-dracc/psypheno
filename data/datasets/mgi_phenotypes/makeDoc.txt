#! /bin/zsh

wget 'https://www.informatics.jax.org/downloads/reports/MGI_PhenotypicAllele.rpt'
wget 'https://www.informatics.jax.org/downloads/reports/mp.json'

./add_phenotype_names.py
