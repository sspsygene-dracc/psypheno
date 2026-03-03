#!/usr/bin/env python3
"""
Verification of CCT and HMP implementations against R reference code.

This script:
1. Reimplements the R reference functions (ACAT/STAAR CCT and harmonicmeanp p.hmp)
   as faithfully as possible in Python.
2. Implements our production Python versions.
3. Runs comprehensive test scenarios and compares outputs.
4. Generates an HTML report with all results.
"""

import json
import math
import sys
from typing import Any

import numpy as np
from scipy.stats import cauchy as cauchy_dist
from scipy.special import digamma


# =============================================================================
# PART 1: Our production implementations (from combined_pvalues.py)
# =============================================================================

def our_cauchy_combination(pvalues: np.ndarray) -> float:
    """Our production CCT implementation."""
    weights = np.ones(len(pvalues)) / len(pvalues)
    p_clamped = np.clip(pvalues, 1e-300, 1.0 - 1e-15)
    t_stat = np.sum(weights * np.tan((0.5 - p_clamped) * np.pi))
    combined_p = cauchy_dist.sf(t_stat)
    return float(np.clip(combined_p, 0.0, 1.0))


def our_harmonic_mean_pvalue(pvalues: np.ndarray) -> float:
    """Our production HMP implementation."""
    n = len(pvalues)
    weights = np.ones(n) / n
    hmp = np.sum(weights) / np.sum(weights / pvalues)
    return min(float(hmp), 1.0)


# =============================================================================
# PART 2: R Reference Reimplementations
# =============================================================================

# ---------------------------------------------------------------------------
# CCT: Faithful Python translation of STAAR::CCT (xihaoli/STAAR/R/CCT.R)
# This is the cleaner implementation; ACAT() from yaowuliu/ACAT is equivalent
# for vector inputs with equal weights.
# ---------------------------------------------------------------------------

def r_ref_cct(pvals: np.ndarray, weights: np.ndarray | None = None) -> float:
    """
    Faithful Python translation of STAAR::CCT.

    R source (STAAR/R/CCT.R):
        CCT <- function(pvals, weights=NULL){
          if(sum(is.na(pvals)) > 0) stop(...)
          if((sum(pvals<0) + sum(pvals>1)) > 0) stop(...)
          is.zero <- (sum(pvals==0)>=1)
          is.one <- (sum(pvals==1)>=1)
          if(is.zero && is.one) stop(...)
          if(is.zero) return(0)
          if(is.one){ warning(...); return(1) }
          if(is.null(weights)){
            weights <- rep(1/length(pvals),length(pvals))
          } else { ... weights <- weights/sum(weights) }
          is.small <- (pvals < 1e-16)
          if (sum(is.small) == 0){
            cct.stat <- sum(weights*tan((0.5-pvals)*pi))
          } else {
            cct.stat <- sum((weights[is.small]/pvals[is.small])/pi)
            cct.stat <- cct.stat + sum(weights[!is.small]*tan((0.5-pvals[!is.small])*pi))
          }
          if(cct.stat > 1e+15){
            pval <- (1/cct.stat)/pi
          } else {
            pval <- 1-pcauchy(cct.stat)
          }
          return(pval)
        }
    """
    pvals = np.asarray(pvals, dtype=float)

    # Check for NAs
    if np.any(np.isnan(pvals)):
        raise ValueError("Cannot have NAs in the p-values!")

    # Check range
    if np.any(pvals < 0) or np.any(pvals > 1):
        raise ValueError("All p-values must be between 0 and 1!")

    # Check for exact 0 and 1
    is_zero = np.any(pvals == 0.0)
    is_one = np.any(pvals == 1.0)
    if is_zero and is_one:
        raise ValueError("Cannot have both 0 and 1 p-values!")
    if is_zero:
        return 0.0
    if is_one:
        return 1.0

    # Default: equal weights
    if weights is None:
        w = np.ones(len(pvals)) / len(pvals)
    else:
        w = np.asarray(weights, dtype=float)
        w = w / np.sum(w)

    # Handle very small p-values differently (key difference from our impl)
    is_small = pvals < 1e-16
    if not np.any(is_small):
        cct_stat = np.sum(w * np.tan((0.5 - pvals) * np.pi))
    else:
        cct_stat = np.sum((w[is_small] / pvals[is_small]) / np.pi)
        cct_stat += np.sum(w[~is_small] * np.tan((0.5 - pvals[~is_small]) * np.pi))

    # Handle very large test statistic
    if cct_stat > 1e15:
        pval = (1.0 / cct_stat) / np.pi
    else:
        # 1 - pcauchy(cct_stat) = survival function
        pval = cauchy_dist.sf(cct_stat)

    return float(pval)


# ---------------------------------------------------------------------------
# CCT: Faithful Python translation of yaowuliu/ACAT::ACAT
# (the original author's implementation, handles matrix input but we use
# vector mode only for comparison)
# ---------------------------------------------------------------------------

def r_ref_acat(pvals: np.ndarray, weights: np.ndarray | None = None) -> float:
    """
    Faithful Python translation of ACAT::ACAT (vector mode only).

    Key differences from STAAR::CCT:
    - Uses 1e-15 as the small-p threshold (vs 1e-16 in STAAR)
    - Uses colMeans instead of colSums (equivalent with normalized weights for equal-weight case)
    - Does not have the large-statistic shortcut
    """
    pvals = np.asarray(pvals, dtype=float)

    if np.any(np.isnan(pvals)):
        raise ValueError("Cannot have NAs in the p-values!")
    if np.any(pvals < 0) or np.any(pvals > 1):
        raise ValueError("P-values must be between 0 and 1!")

    is_zero = np.any(pvals == 0.0)
    is_one = np.any(pvals == 1.0)
    if is_zero and is_one:
        raise ValueError("Cannot have both 0 and 1 p-values in the same column!")

    # Default: equal weights (uses colMeans, i.e., w_i = 1/n)
    if weights is None:
        is_weights_null = True
    else:
        is_weights_null = False
        w = np.asarray(weights, dtype=float)
        w = w / np.sum(w)

    # Threshold for small p-values: 1e-15 in ACAT (vs 1e-16 in STAAR)
    is_small = pvals < 1e-15

    if is_weights_null:
        vals = pvals.copy()
        vals[~is_small] = np.tan((0.5 - vals[~is_small]) * np.pi)
        vals[is_small] = 1.0 / vals[is_small] / np.pi
        cct_stat = np.mean(vals)  # colMeans for vector = mean
    else:
        vals = pvals.copy()
        vals[~is_small] = w[~is_small] * np.tan((0.5 - pvals[~is_small]) * np.pi)
        vals[is_small] = (w[is_small] / pvals[is_small]) / np.pi
        cct_stat = np.sum(vals)

    # pcauchy(cct_stat, lower.tail=FALSE)
    pval = cauchy_dist.sf(cct_stat)
    return float(pval)


# ---------------------------------------------------------------------------
# HMP: Faithful Python translation of harmonicmeanp::p.hmp
# (Daniel Wilson, CRAN package harmonicmeanp v3.0+)
# ---------------------------------------------------------------------------

def r_ref_hmp_stat(p: np.ndarray, w: np.ndarray | None = None) -> float:
    """
    Faithful translation of harmonicmeanp::hmp.stat

    R source:
        hmp.stat = function(p, w = NULL) {
            p = as.numeric(p)
            if (is.null(w)) return(c(hmp.stat = 1/mean(1/p)))
            return(c(hmp.stat = sum(w)/sum(w/p)))
        }
    """
    p = np.asarray(p, dtype=float)
    if w is None:
        return float(1.0 / np.mean(1.0 / p))
    w = np.asarray(w, dtype=float)
    return float(np.sum(w) / np.sum(w / p))


def r_ref_p_hmp(p: np.ndarray, w: np.ndarray | None = None,
                L: int | None = None, multilevel: bool = True) -> float:
    """
    Faithful Python translation of harmonicmeanp::p.hmp (v3.0+).

    Uses the Landau distribution (stable with alpha=1) for calibration.

    R source:
        p.hmp = function(p, w = NULL, L = NULL, w.sum.tolerance = 1e-6, multilevel = TRUE) {
            if(is.null(L) & multilevel) {
                warning("L not specified: for multilevel testing set L to the total number of individual p-values")
                L = length(p)
            }
            if(length(p) == 0) return(NA)
            if(length(p) > L) warning("The number of p-values cannot exceed L")
            if(is.null(w)) {
                w = rep(1/L,length(p))
            } else if(any(w<0)) {
                stop("No weights can be negative")
            }
            w.sum = sum(w)
            if(w.sum>1+w.sum.tolerance) {
                stop("Weights cannot exceed 1")
            }
            HMP = hmp.stat(p, w)
            O.874 = 1 + digamma(1) - log(2/pi)
            if(multilevel) {
                return(c(p.hmp = w.sum*pEstable(w.sum/HMP, setParam(alpha = 1, location = (log(L) + O.874), logscale = log(pi/2), pm = 0), lower.tail = FALSE)))
            }
            return(c(p.hmp = pEstable(1/HMP, setParam(alpha = 1, location = (log(length(p)) + O.874), logscale = log(pi/2), pm = 0), lower.tail = FALSE)))
        }

    The key operation is evaluating the survival function of a Landau distribution
    (alpha=1 stable) at the reciprocal of the HMP statistic.
    """
    from scipy.stats import levy_stable

    p_arr = np.asarray(p, dtype=float)
    n = len(p_arr)

    if n == 0:
        return float('nan')

    if L is None:
        if multilevel:
            L = n
        else:
            L = n

    if w is None:
        w_arr = np.ones(n) / L
    else:
        w_arr = np.asarray(w, dtype=float)

    w_sum = np.sum(w_arr)

    # Compute HMP statistic
    HMP = r_ref_hmp_stat(p_arr, w_arr)

    # O.874 constant: 1 + digamma(1) - log(2/pi)
    # digamma(1) = -gamma (Euler-Mascheroni) = -0.5772156649...
    # log(2/pi) = log(2) - log(pi) = -0.4515827053...
    O_874 = 1.0 + float(digamma(1.0)) - np.log(2.0 / np.pi)

    # Landau distribution parameters:
    #   alpha = 1 (Cauchy-type stable)
    #   location (mu) = log(L) + O.874
    #   scale (sigma) = pi/2
    #
    # In scipy's levy_stable parametrization (S1):
    #   alpha=1, beta=1 gives a Landau-type distribution
    #   with loc and scale parameters.
    #
    # R's FMStable::pEstable with pm=0 uses the "0-parameterization"
    # (also called S0 or Zolotarev's A parametrization).
    #
    # For alpha=1, the S0 and S1 parametrizations relate as:
    #   S0: location_0, scale
    #   S1: location_1 = location_0 + beta * scale * (2/pi) * log(scale), scale
    #
    # FMStable uses logscale, so scale = exp(logscale) = exp(log(pi/2)) = pi/2
    # Location in S0 (pm=0) is: log(L) + O.874
    #
    # To convert to scipy's S1 parametrization:
    #   loc_S1 = loc_S0 + beta * scale * (2/pi) * ln(scale)
    #   with beta=1, scale=pi/2:
    #   loc_S1 = (log(L) + O.874) + 1 * (pi/2) * (2/pi) * ln(pi/2)
    #   loc_S1 = log(L) + O.874 + ln(pi/2)

    mu_S0 = np.log(L) + O_874
    scale = np.pi / 2.0

    # Convert S0 -> S1 for scipy
    # For alpha=1, beta=1: loc_S1 = loc_S0 + beta * scale * (2/pi) * ln(scale)
    mu_S1 = mu_S0 + 1.0 * scale * (2.0 / np.pi) * np.log(scale)

    if multilevel:
        x = w_sum / HMP
        # p.hmp = w.sum * pEstable(w.sum/HMP, ..., lower.tail=FALSE)
        sf_val = levy_stable.sf(x, alpha=1.0, beta=1.0, loc=mu_S1, scale=scale)
        return float(w_sum * sf_val)
    else:
        x = 1.0 / HMP
        sf_val = levy_stable.sf(x, alpha=1.0, beta=1.0, loc=mu_S1, scale=scale)
        return float(sf_val)


def r_ref_p_hmp_simple(p: np.ndarray) -> float:
    """
    Simplified HMP: just return the harmonic mean with equal weights 1/L.
    This is what our implementation does -- Wilson (2019) Theorem 1 states
    the HMP statistic itself is an asymptotically valid p-value.
    This corresponds to hmp.stat() with default weights.
    """
    return float(1.0 / np.mean(1.0 / p))


# =============================================================================
# PART 3: Test scenarios
# =============================================================================

def generate_test_cases() -> list[dict[str, Any]]:
    """Generate comprehensive test scenarios."""
    np.random.seed(42)

    cases = []

    # Single p-value
    cases.append({"name": "Single p-value (0.05)", "pvals": np.array([0.05])})
    cases.append({"name": "Single p-value (0.5)", "pvals": np.array([0.5])})
    cases.append({"name": "Single p-value (1e-10)", "pvals": np.array([1e-10])})

    # Small sets (2-5 p-values)
    cases.append({"name": "2 small p-values", "pvals": np.array([0.001, 0.005])})
    cases.append({"name": "2 mixed p-values", "pvals": np.array([0.001, 0.8])})
    cases.append({"name": "3 mixed p-values", "pvals": np.array([0.01, 0.05, 0.5])})
    cases.append({"name": "3 small p-values", "pvals": np.array([1e-4, 2e-4, 5e-4])})
    cases.append({"name": "5 typical p-values", "pvals": np.array([0.02, 4e-4, 0.2, 0.1, 0.8])})
    cases.append({"name": "5 all significant", "pvals": np.array([0.001, 0.003, 0.008, 0.005, 0.01])})

    # Medium sets (10 p-values)
    cases.append({"name": "10 uniform random", "pvals": np.random.uniform(0.0001, 1.0, 10)})
    cases.append({"name": "10 all small (<0.01)", "pvals": np.random.uniform(1e-6, 0.01, 10)})
    cases.append({"name": "10 all large (>0.5)", "pvals": np.random.uniform(0.5, 0.99, 10)})
    cases.append({"name": "10 mixed (5 small, 5 large)", "pvals": np.concatenate([
        np.random.uniform(1e-5, 0.01, 5), np.random.uniform(0.5, 0.99, 5)
    ])})

    # Larger sets
    cases.append({"name": "50 uniform random", "pvals": np.random.uniform(0.0001, 1.0, 50)})
    cases.append({"name": "50 mostly non-significant", "pvals": np.concatenate([
        np.random.uniform(0.3, 0.99, 45), np.random.uniform(1e-5, 0.01, 5)
    ])})
    cases.append({"name": "100 uniform random", "pvals": np.random.uniform(0.0001, 1.0, 100)})
    cases.append({"name": "100 all small", "pvals": np.random.uniform(1e-8, 0.01, 100)})

    # Extreme p-values
    cases.append({"name": "Extreme: very small", "pvals": np.array([1e-20, 1e-15, 1e-10, 1e-5])})
    cases.append({"name": "Extreme: near zero", "pvals": np.array([1e-100, 1e-50, 1e-30, 1e-20, 1e-10])})
    cases.append({"name": "Extreme: near one", "pvals": np.array([0.99, 0.999, 0.9999, 0.95])})
    cases.append({"name": "Extreme: mixed extremes", "pvals": np.array([1e-20, 0.9999])})
    cases.append({"name": "Extreme: single very small", "pvals": np.array([1e-300, 0.5, 0.8, 0.9])})

    # Edge cases
    cases.append({"name": "All identical (0.05)", "pvals": np.array([0.05, 0.05, 0.05, 0.05, 0.05])})
    cases.append({"name": "All identical (0.5)", "pvals": np.array([0.5, 0.5, 0.5, 0.5])})
    cases.append({"name": "Descending powers of 10", "pvals": np.array([0.1, 0.01, 0.001, 0.0001, 0.00001])})

    return cases


# =============================================================================
# PART 4: Run all comparisons and collect results
# =============================================================================

def relative_diff(a: float, b: float) -> float:
    """Compute relative difference between two values."""
    if a == 0 and b == 0:
        return 0.0
    if a == 0 or b == 0:
        return float('inf')
    return abs(a - b) / max(abs(a), abs(b))


def run_all_tests() -> dict[str, Any]:
    """Run all test cases and return structured results."""
    cases = generate_test_cases()

    cct_results = []
    hmp_results = []

    for case in cases:
        pvals = case["pvals"]
        name = case["name"]

        # --- CCT comparison ---
        our_cct = our_cauchy_combination(pvals)
        try:
            ref_cct_staar = r_ref_cct(pvals)
        except Exception as e:
            ref_cct_staar = f"ERROR: {e}"
        try:
            ref_cct_acat = r_ref_acat(pvals)
        except Exception as e:
            ref_cct_acat = f"ERROR: {e}"

        rd_staar = relative_diff(our_cct, ref_cct_staar) if isinstance(ref_cct_staar, float) else None
        rd_acat = relative_diff(our_cct, ref_cct_acat) if isinstance(ref_cct_acat, float) else None

        cct_results.append({
            "name": name,
            "n": len(pvals),
            "our": our_cct,
            "ref_staar": ref_cct_staar,
            "ref_acat": ref_cct_acat,
            "rd_staar": rd_staar,
            "rd_acat": rd_acat,
        })

        # --- HMP comparison ---
        our_hmp = our_harmonic_mean_pvalue(pvals)
        hmp_stat_val = r_ref_hmp_stat(pvals)  # just the harmonic mean (no weights = 1/mean(1/p))
        hmp_simple = r_ref_p_hmp_simple(pvals)

        # p.hmp with default L=n, multilevel=TRUE (the full R function)
        try:
            ref_p_hmp_ml = r_ref_p_hmp(pvals, L=None, multilevel=True)
        except Exception as e:
            ref_p_hmp_ml = f"ERROR: {e}"

        # p.hmp with multilevel=FALSE
        try:
            ref_p_hmp_noml = r_ref_p_hmp(pvals, L=None, multilevel=False)
        except Exception as e:
            ref_p_hmp_noml = f"ERROR: {e}"

        rd_stat = relative_diff(our_hmp, hmp_stat_val)
        rd_p_hmp_ml = relative_diff(our_hmp, ref_p_hmp_ml) if isinstance(ref_p_hmp_ml, float) else None
        rd_p_hmp_noml = relative_diff(our_hmp, ref_p_hmp_noml) if isinstance(ref_p_hmp_noml, float) else None

        hmp_results.append({
            "name": name,
            "n": len(pvals),
            "our": our_hmp,
            "hmp_stat": hmp_stat_val,
            "hmp_simple": hmp_simple,
            "p_hmp_multilevel": ref_p_hmp_ml,
            "p_hmp_no_multilevel": ref_p_hmp_noml,
            "rd_stat": rd_stat,
            "rd_p_hmp_ml": rd_p_hmp_ml,
            "rd_p_hmp_noml": rd_p_hmp_noml,
        })

    return {
        "cct_results": cct_results,
        "hmp_results": hmp_results,
    }


def main():
    print("Running CCT/HMP verification tests...")
    print("=" * 80)
    results = run_all_tests()

    # Print CCT results
    print("\n\nCCT RESULTS")
    print("=" * 120)
    print(f"{'Test Case':<35} {'N':>3} {'Our CCT':>14} {'R:STAAR CCT':>14} {'R:ACAT':>14} {'RelDiff(STAAR)':>15} {'RelDiff(ACAT)':>15}")
    print("-" * 120)
    for r in results["cct_results"]:
        staar_str = f"{r['ref_staar']:.6e}" if isinstance(r['ref_staar'], float) else str(r['ref_staar'])[:14]
        acat_str = f"{r['ref_acat']:.6e}" if isinstance(r['ref_acat'], float) else str(r['ref_acat'])[:14]
        rd_s = f"{r['rd_staar']:.2e}" if r['rd_staar'] is not None else "N/A"
        rd_a = f"{r['rd_acat']:.2e}" if r['rd_acat'] is not None else "N/A"
        print(f"{r['name']:<35} {r['n']:>3} {r['our']:>14.6e} {staar_str:>14} {acat_str:>14} {rd_s:>15} {rd_a:>15}")

    # Print HMP results
    print("\n\nHMP RESULTS")
    print("=" * 140)
    print(f"{'Test Case':<35} {'N':>3} {'Our HMP':>14} {'hmp.stat()':>14} {'p.hmp(ml)':>14} {'p.hmp(no-ml)':>14} {'RD(stat)':>10} {'RD(p.hmp ml)':>14} {'RD(p.hmp noml)':>14}")
    print("-" * 140)
    for r in results["hmp_results"]:
        phmp_ml = f"{r['p_hmp_multilevel']:.6e}" if isinstance(r['p_hmp_multilevel'], float) else str(r['p_hmp_multilevel'])[:14]
        phmp_noml = f"{r['p_hmp_no_multilevel']:.6e}" if isinstance(r['p_hmp_no_multilevel'], float) else str(r['p_hmp_no_multilevel'])[:14]
        rd_s = f"{r['rd_stat']:.2e}" if r['rd_stat'] is not None else "N/A"
        rd_ml = f"{r['rd_p_hmp_ml']:.2e}" if r['rd_p_hmp_ml'] is not None else "N/A"
        rd_noml = f"{r['rd_p_hmp_noml']:.2e}" if r['rd_p_hmp_noml'] is not None else "N/A"
        print(f"{r['name']:<35} {r['n']:>3} {r['our']:>14.6e} {r['hmp_stat']:>14.6e} {phmp_ml:>14} {phmp_noml:>14} {rd_s:>10} {rd_ml:>14} {rd_noml:>14}")

    # Output as JSON for report generation
    # Convert numpy types to native Python for JSON serialization
    def sanitize(obj):
        if isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        return obj

    with open("/Users/jbirgmei/prog/sspsygene/reports/verification_results.json", "w") as f:
        json.dump(sanitize(results), f, indent=2, default=str)

    print(f"\n\nResults saved to verification_results.json")

    # Summary statistics
    print("\n\nSUMMARY")
    print("=" * 80)

    cct_rd_staar = [r['rd_staar'] for r in results['cct_results'] if r['rd_staar'] is not None and r['rd_staar'] != float('inf')]
    cct_rd_acat = [r['rd_acat'] for r in results['cct_results'] if r['rd_acat'] is not None and r['rd_acat'] != float('inf')]

    if cct_rd_staar:
        print(f"\nCCT vs STAAR::CCT:")
        print(f"  Max relative difference: {max(cct_rd_staar):.2e}")
        print(f"  Mean relative difference: {np.mean(cct_rd_staar):.2e}")
        print(f"  Median relative difference: {np.median(cct_rd_staar):.2e}")
        n_close = sum(1 for rd in cct_rd_staar if rd < 1e-10)
        print(f"  Tests with RelDiff < 1e-10: {n_close}/{len(cct_rd_staar)}")

    if cct_rd_acat:
        print(f"\nCCT vs ACAT::ACAT:")
        print(f"  Max relative difference: {max(cct_rd_acat):.2e}")
        print(f"  Mean relative difference: {np.mean(cct_rd_acat):.2e}")
        print(f"  Median relative difference: {np.median(cct_rd_acat):.2e}")
        n_close = sum(1 for rd in cct_rd_acat if rd < 1e-10)
        print(f"  Tests with RelDiff < 1e-10: {n_close}/{len(cct_rd_acat)}")

    hmp_rd_stat = [r['rd_stat'] for r in results['hmp_results'] if r['rd_stat'] is not None and r['rd_stat'] != float('inf')]
    if hmp_rd_stat:
        print(f"\nHMP vs hmp.stat() (harmonic mean only):")
        print(f"  Max relative difference: {max(hmp_rd_stat):.2e}")
        print(f"  Mean relative difference: {np.mean(hmp_rd_stat):.2e}")
        print(f"  Tests with RelDiff < 1e-10: {sum(1 for rd in hmp_rd_stat if rd < 1e-10)}/{len(hmp_rd_stat)}")

    hmp_rd_ml = [r['rd_p_hmp_ml'] for r in results['hmp_results'] if r['rd_p_hmp_ml'] is not None and not isinstance(r['rd_p_hmp_ml'], str) and r['rd_p_hmp_ml'] != float('inf')]
    if hmp_rd_ml:
        print(f"\nHMP vs p.hmp() (full Landau-calibrated, multilevel):")
        print(f"  Max relative difference: {max(hmp_rd_ml):.2e}")
        print(f"  Mean relative difference: {np.mean(hmp_rd_ml):.2e}")
        print(f"  This measures how much our simple HMP differs from the Landau-calibrated version.")


if __name__ == "__main__":
    main()
