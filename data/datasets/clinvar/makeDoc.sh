#!/usr/bin/env bash
# Provenance for the clinvar dataset.
#
# Source page: https://www.ncbi.nlm.nih.gov/clinvar/
# Source FTP:  https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/
# File:        gene_specific_summary.txt
# Cadence:     refreshed ~weekly by NCBI; the file's first line
#              ("#Overview of data in ClinVar by gene, dated <date>")
#              records the snapshot date.
#
# preprocess.py downloads this file automatically at build time, so
# the rebuild stays reproducible without committing the raw input. This
# script is the durable provenance record — running it manually fetches
# the same file preprocess.py would, into the dataset directory.
#
# Issue: https://github.com/sspsygene-dracc/psypheno/issues/4
#         (Stephan Sanders ask for ClinVar P/LP / VUS / conflict counts)

set -euo pipefail

cd "$(dirname "$0")"

curl -fLO https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/gene_specific_summary.txt
