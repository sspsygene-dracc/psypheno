#! /bin/zsh

cat 1-s2.0-S1934590925003741-mmc11.txt | cut -f 2- > s11.tsv
dos2unix s11.tsv

cat nebula_gene_0.2_FDR.txt | cut -f 2- > nebula_gene_0.2_FDR.tsv
dos2unix nebula_gene_0.2_FDR.tsv

cat "Patient List - Sheet1.tsv" | sed 's/n\/a/not_available/g' > patient_list.tsv
