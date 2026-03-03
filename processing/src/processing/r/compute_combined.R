#!/usr/bin/env Rscript
#
# Compute combined p-values per gene across datasets.
#
# Called by Python via subprocess. Reads input CSVs from a temp directory,
# computes Fisher, Stouffer, CCT, and HMP combined p-values per gene,
# applies BH FDR correction, and writes results CSV.
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

# --- Check required packages ---
check_package <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(paste0(
      "R package '", pkg, "' is not installed.\n",
      "Install with: Rscript -e 'install.packages(\"", pkg, "\")'"
    ), call. = FALSE)
  }
}
check_package("harmonicmeanp")

# --- CCT implementation (faithful to STAAR::CCT by Xihao Li) ---
# Source: https://github.com/xihaoli/STAAR/blob/master/R/CCT.R
# We include this directly to avoid depending on the STAAR Bioconductor package
# or the ACAT package (removed from CRAN for R >= 4.5).
cct <- function(pvals, weights = NULL) {
  if (any(is.na(pvals))) stop("Cannot have NAs in p-values")
  if (any(pvals < 0) || any(pvals > 1)) stop("P-values must be in [0, 1]")

  is_zero <- any(pvals == 0)
  is_one  <- any(pvals == 1)
  if (is_zero && is_one) stop("Cannot have both 0 and 1 p-values")
  if (is_zero) return(0)
  if (is_one)  return(1)

  if (is.null(weights)) {
    weights <- rep(1 / length(pvals), length(pvals))
  } else {
    weights <- weights / sum(weights)
  }

  # For very small p-values, use Taylor approximation:
  # tan((0.5 - p) * pi) ~ 1/(p * pi)  when p -> 0
  is_small <- (pvals < 1e-16)
  if (!any(is_small)) {
    cct_stat <- sum(weights * tan((0.5 - pvals) * pi))
  } else {
    cct_stat <- sum((weights[is_small] / pvals[is_small]) / pi)
    if (any(!is_small)) {
      cct_stat <- cct_stat + sum(weights[!is_small] * tan((0.5 - pvals[!is_small]) * pi))
    }
  }

  # For very large test statistics, use Cauchy tail approximation
  if (cct_stat > 1e+15) {
    pval <- (1 / cct_stat) / pi
  } else {
    pval <- pcauchy(cct_stat, lower.tail = FALSE)
  }

  return(pval)
}

# --- Fisher's method (base R) ---
fisher_combine <- function(pvals) {
  # pvals: vector of collapsed per-table p-values
  # Filter out 1.0 (contribute no information: ln(1) = 0)
  valid <- pvals[pvals < 1.0]
  if (length(valid) < 2) return(NA_real_)
  stat <- -2 * sum(log(valid))
  pchisq(stat, df = 2 * length(valid), lower.tail = FALSE)
}

# --- Stouffer's method (base R) ---
stouffer_combine <- function(pvals) {
  valid <- pvals[pvals < 1.0]
  if (length(valid) < 2) return(NA_real_)
  z <- sum(qnorm(1 - valid)) / sqrt(length(valid))
  pnorm(z, lower.tail = FALSE)
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
    fisher_p[i]   <- fisher_combine(cp)
    stouffer_p[i] <- stouffer_combine(cp)
  }

  # Raw p-values for CCT/HMP
  rp <- raw_by_gene[[gid_str]]
  if (!is.null(rp) && length(rp) > 0) {
    cauchy_p[i] <- tryCatch(cct(rp), error = function(e) NA_real_)
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

# Write results
results <- data.frame(
  gene_id      = gene_ids,
  fisher_p     = fisher_p,
  stouffer_p   = stouffer_p,
  cauchy_p     = cauchy_p,
  hmp_p        = hmp_p,
  fisher_fdr   = fisher_fdr,
  stouffer_fdr = stouffer_fdr,
  cauchy_fdr   = cauchy_fdr,
  hmp_fdr      = hmp_fdr
)

output_file <- file.path(temp_dir, "results.csv")
write.csv(results, output_file, row.names = FALSE)

cat(sprintf("  R: Wrote results for %d genes to %s\n", n_genes, output_file))
