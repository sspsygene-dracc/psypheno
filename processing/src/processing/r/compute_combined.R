#!/usr/bin/env Rscript
#
# Compute combined p-values per gene across datasets.
#
# Called by Python via subprocess. Reads input CSVs from a temp directory,
# computes Fisher, Stouffer, CCT, and HMP combined p-values per gene,
# applies BH FDR correction, and writes results CSV.
#
# All statistical methods use reviewed R package implementations:
#   - Fisher's method:    poolr::fisher()
#   - Stouffer's method:  poolr::stouffer()
#   - CCT:                ACAT::ACAT()
#   - HMP:                harmonicmeanp::p.hmp()
#   - BH FDR:             stats::p.adjust(method="BH")
#
# Usage: Rscript compute_combined.R <temp_dir>
#
# Input files in temp_dir:
#   collapsed_pvalues.csv  — gene_id, pvalue (one row per gene-table pair)
#   raw_pvalues.csv        — gene_id, pvalue (one row per raw p-value)
#
# Output file in temp_dir:
#   results.csv — gene_id, fisher_p, stouffer_p, cauchy_p, hmp_p,
#                 fisher_fdr, stouffer_fdr, cauchy_fdr, hmp_fdr

# --- Add project-local R library (for non-writable system library) ---
script_args <- commandArgs(trailingOnly = FALSE)
file_arg <- script_args[grep("^--file=", script_args)]
if (length(file_arg) > 0) {
  script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[1])))
  local_lib <- file.path(script_dir, "lib")
  if (dir.exists(local_lib)) {
    .libPaths(c(local_lib, .libPaths()))
  }
}

# --- Load required packages ---
required_packages <- c("poolr", "ACAT", "harmonicmeanp")
for (pkg in required_packages) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(paste0(
      "R package '", pkg, "' is not installed.\n",
      "Install with: Rscript -e 'install.packages(\"", pkg, "\")'"
    ), call. = FALSE)
  }
}

# --- Wrappers that match our pipeline conventions ---

fisher_combine <- function(pvals) {
  # Filter out 1.0 (contribute no information: ln(1) = 0)
  valid <- pvals[pvals < 1.0]
  if (length(valid) < 2) return(NA_real_)
  poolr::fisher(valid)$p
}

stouffer_combine <- function(pvals) {
  valid <- pvals[pvals < 1.0]
  if (length(valid) < 2) return(NA_real_)
  poolr::stouffer(valid)$p
}

# --- Main ---
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) {
  stop("Usage: Rscript compute_combined.R <temp_dir>", call. = FALSE)
}
temp_dir <- args[1]

collapsed_file <- file.path(temp_dir, "collapsed_pvalues.csv")
raw_file       <- file.path(temp_dir, "raw_pvalues.csv")

if (!file.exists(collapsed_file)) stop(paste("Missing:", collapsed_file))
if (!file.exists(raw_file))       stop(paste("Missing:", raw_file))

# Read input
collapsed <- read.csv(collapsed_file, colClasses = c("integer", "numeric"))
raw       <- read.csv(raw_file,       colClasses = c("integer", "numeric"))

# Get unique gene IDs (union of both files)
gene_ids <- sort(unique(c(collapsed$gene_id, raw$gene_id)))
n_genes <- length(gene_ids)

cat(sprintf("  R: Processing %d genes...\n", n_genes))

# Pre-allocate result vectors
fisher_p   <- rep(NA_real_, n_genes)
stouffer_p <- rep(NA_real_, n_genes)
cauchy_p   <- rep(NA_real_, n_genes)
hmp_p      <- rep(NA_real_, n_genes)

# Split data by gene for fast lookup
collapsed_by_gene <- split(collapsed$pvalue, collapsed$gene_id)
raw_by_gene       <- split(raw$pvalue, raw$gene_id)

for (i in seq_along(gene_ids)) {
  gid <- gene_ids[i]
  gid_str <- as.character(gid)

  # Collapsed p-values for Fisher/Stouffer
  cp <- collapsed_by_gene[[gid_str]]
  if (!is.null(cp) && length(cp) > 0) {
    fisher_p[i]   <- tryCatch(fisher_combine(cp), error = function(e) NA_real_)
    stouffer_p[i] <- tryCatch(stouffer_combine(cp), error = function(e) NA_real_)
  }

  # Raw p-values for CCT/HMP
  rp <- raw_by_gene[[gid_str]]
  if (!is.null(rp) && length(rp) > 0) {
    cauchy_p[i] <- tryCatch(ACAT::ACAT(rp), error = function(e) NA_real_)
    hmp_p[i]    <- tryCatch(
      harmonicmeanp::p.hmp(rp, L = length(rp)),
      error = function(e) NA_real_
    )
  }
}

cat("  R: Computing BH FDR corrections...\n")

# BH FDR correction (handles NAs gracefully)
fisher_fdr   <- p.adjust(fisher_p,   method = "BH")
stouffer_fdr <- p.adjust(stouffer_p, method = "BH")
cauchy_fdr   <- p.adjust(cauchy_p,   method = "BH")
hmp_fdr      <- p.adjust(hmp_p,      method = "BH")

# Format p-values with full double precision (17 significant digits)
# to avoid write.csv's default ~5-digit rounding, which can make
# CCT and HMP appear identical when they differ only in low-order digits.
fmt <- function(x) ifelse(is.na(x), NA_character_, sprintf("%.17e", x))

results <- data.frame(
  gene_id      = gene_ids,
  fisher_p     = fmt(fisher_p),
  stouffer_p   = fmt(stouffer_p),
  cauchy_p     = fmt(cauchy_p),
  hmp_p        = fmt(hmp_p),
  fisher_fdr   = fmt(fisher_fdr),
  stouffer_fdr = fmt(stouffer_fdr),
  cauchy_fdr   = fmt(cauchy_fdr),
  hmp_fdr      = fmt(hmp_fdr),
  stringsAsFactors = FALSE
)

output_file <- file.path(temp_dir, "results.csv")
write.csv(results, output_file, row.names = FALSE)

cat(sprintf("  R: Wrote results for %d genes to %s\n", n_genes, output_file))
