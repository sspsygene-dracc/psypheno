# Using FDR Information Rigorously in Meta-Analysis

## Background and the Core Problem

In a single differential expression study, p-values are computed for each gene, and adjusted p-values (FDR / q-values) are derived from them via methods like Benjamini–Hochberg (BH). The interpretation of FDR is precise: among genes called significant at adjusted-p ≤ α, the *expected* proportion of false positives is at most α. (Note that Bonferroni controls the family-wise error rate, FWER — the probability of *any* false positive — and is a different beast from BH-style FDR control, even though both produce "adjusted p-values".)

Several methods exist for combining p-values across studies in meta-analysis: Fisher, Stouffer, Cauchy Combination Test (CCT), Harmonic Mean P (HMP). These rely on the fact that under the null, p-values are uniform on $[0,1]$, which gives a clean basis for combination.

There is, however, no analogous framework for combining FDR / q-values directly. The reason is structural: q-values are not pivotal quantities. Their distribution depends on the unknown proportion of true nulls $\pi_0$ and on the dependence structure within each study, so there is no "U[0,1] under the null" analog to anchor a combination rule.

This raises the central question: per-study FDR values encode meaningful information about each experiment (its noise floor, its power, its multiple-testing burden). Discarding that information seems wasteful. How can we use it rigorously in a meta-analysis?

The honest answer involves a reframing. FDR and FWER are *conditional* on the information set used to compute them. A per-study FDR of 0.01 means "given only this study's evidence, the expected false discovery proportion is 1%." When studies are combined, the information set changes, so the appropriate error-rate-controlled set changes too. The rigorous move is therefore not to combine FDRs directly, but to combine the underlying evidence (p-values, z-scores, or effect sizes) and re-derive error control on the larger information set. The per-study FDR is a *summary* of that study's evidence; the underlying evidence is what flows into the meta-analysis.

The remainder of this report develops the main approaches, the math behind them, and the practical considerations.

---

## 1. Combine P-Values, Then Re-Apply FDR Control

For gene $g$ in study $i$, let $p_{gi}$ be the p-value. Compute one meta p-value per gene, $p_g^{\text{meta}}$, then apply BH across genes.

### Fisher's method

Under the null, $-2\ln p_i \sim \chi^2_2$, so

$$X_g = -2 \sum_{i=1}^K \ln p_{gi} \sim \chi^2_{2K} \text{ under the global null.}$$

Sensitive to a single very small p-value. Assumes independence across studies.

### Stouffer's method

Convert each p-value to a z-score via $z_i = \Phi^{-1}(1 - p_i)$, then

$$Z_g = \frac{\sum_i w_i z_{gi}}{\sqrt{\sum_i w_i^2}} \sim \mathcal{N}(0,1) \text{ under the null.}$$

Weights $w_i$ are typically $\sqrt{n_i}$ or $\sqrt{n_i^{\text{eff}}}$. More balanced than Fisher — won't be hijacked by one outlier. Also assumes independence.

### Cauchy Combination Test (CCT)

$$T_g = \frac{1}{K}\sum_i \tan\bigl((0.5 - p_{gi})\pi\bigr).$$

The remarkable property: $T_g$ is approximately Cauchy in the tail *even under arbitrary dependence*. No independence assumption required.

### Harmonic Mean P (HMP)

$$\text{HMP} = \frac{K}{\sum_i 1/p_{gi}},$$

asymptotically Landau-distributed, also robust to dependence, well-suited when only a fraction of studies are expected to show signal.

### Then apply BH

Sort meta p-values $p_{(1)}^{\text{meta}} \le \ldots \le p_{(G)}^{\text{meta}}$, find the largest $k$ with $p_{(k)}^{\text{meta}} \le \alpha k / G$, and reject all genes up to $k$. This gives FDR control on the meta-level discovery set, which is the inferential target you actually want.

---

## 2. Local FDR Combination

This is the most principled answer to the question of how per-study FDR-style information can flow into a meta-analysis.

### Setup

Model the test statistics (z-scores) as a two-component mixture:

$$f(z) = \pi_0 f_0(z) + (1-\pi_0) f_1(z),$$

where $\pi_0$ is the prior probability of being null, $f_0$ is the null density (typically $\mathcal{N}(0,1)$, possibly empirically estimated), and $f_1$ is the alternative density.

### Local FDR vs. tail-area FDR

Efron's **local FDR** is a *pointwise posterior*:

$$\text{lfdr}(z) = P(H = 0 \mid Z = z) = \frac{\pi_0 f_0(z)}{f(z)}.$$

The **tail-area FDR** (q-value) is an *expectation over a rejection region*. Rejecting all genes with $|Z| \ge z$:

$$\text{Fdr}(z) = P(H = 0 \mid |Z| \ge z) = \frac{\pi_0 \, S_0(z)}{S(z)},$$

where $S_0(z) = P_0(|Z| \ge z)$ is the null survival function (= two-sided p-value of $z$) and $S(z) = P(|Z| \ge z)$ is the marginal survival function.

The two are related by an averaging operation:

$$\text{Fdr}(z) = \frac{\int_{|u| \ge z} \pi_0 f_0(u) \, du}{\int_{|u| \ge z} f(u) \, du} = \frac{\int_{|u| \ge z} \text{lfdr}(u) f(u) \, du}{\int_{|u| \ge z} f(u) \, du} = E\bigl[\text{lfdr}(Z) \mid |Z| \ge z\bigr].$$

That is, the q-value at threshold $z$ is the conditional expectation of the local fdr, given that the statistic falls in the rejection region. lfdr is the integrand; q-value is the integral.

### Why this matters for combinability

Bayes' rule combines posteriors at a point under conditional independence:

$$P(H_g = 0 \mid Z_{g,1}, \ldots, Z_{g,K}) = \frac{\pi_0^K \prod_i f_0(z_{gi})}{\pi_0^K \prod_i f_0(z_{gi}) + (1-\pi_0)^K \prod_i f_1(z_{gi})}.$$

A bit of algebra gives the meta posterior odds of being null as a product of per-study posterior odds:

$$\text{lfdr}^{\text{meta}}_g \;\propto\; \prod_{i=1}^K \frac{\text{lfdr}_i(z_{gi})}{1 - \text{lfdr}_i(z_{gi})}.$$

This works because each $\text{lfdr}_i(z_{gi})$ is a likelihood ratio at a point, and likelihood ratios multiply across independent observations. Q-values are integrals over different regions in different studies, so there is no analogous combination rule — the mathematical object isn't of the right type.

### Estimation and decision rule

The R package `locfdr` fits $f$ nonparametrically (Poisson regression on the z-score histogram), estimates $\pi_0$ from the central peak, and returns $\text{lfdr}(z_g)$ for every gene. Reject genes with $\text{lfdr}^{\text{meta}}_g \le c$, choosing $c$ so that the Bayes FDR over the rejection set, $\text{mean}(\text{lfdr}^{\text{meta}}_g)$ for rejected genes, is $\le \alpha$.

### Sanity check on the relation

Take $\pi_0 = 0.9$, null $\mathcal{N}(0,1)$, alternative $\mathcal{N}(3,1)$. At $z = 3$:

$$\text{lfdr}(3) = \frac{0.9 \cdot \phi(3)}{0.9 \phi(3) + 0.1 \phi(0)} \approx \frac{0.9 \cdot 0.0044}{0.9 \cdot 0.0044 + 0.1 \cdot 0.399} \approx 0.090.$$

For tail-Fdr at $z=3$: $S_0(3) \approx 0.0027$, $S_1(3) \approx 0.5$, so $S(3) \approx 0.0524$, and

$$\text{Fdr}(3) \approx \frac{0.9 \cdot 0.0027}{0.0524} \approx 0.046.$$

$\text{Fdr}(3) < \text{lfdr}(3)$ because the tail average includes more extreme z's where lfdr is much smaller. That gap is the averaging made visible.

---

## 3. Hierarchical / Empirical-Bayes Models

The general structure: for gene $g$, study $i$, observe an effect-size estimate $\hat\beta_{gi}$ with standard error $s_{gi}$. The model:

$$\hat\beta_{gi} \mid \beta_{gi} \sim \mathcal{N}(\beta_{gi}, s_{gi}^2),$$
$$\beta_{gi} \mid \mu_g, \tau_g^2 \sim \mathcal{N}(\mu_g, \tau_g^2),$$
$$\mu_g, \tau_g^2 \sim \text{prior}.$$

$\mu_g$ is the gene's true cross-study effect; $\tau_g^2$ is between-study heterogeneity. The meta-analytic test is on $\mu_g \neq 0$.

**limma (within-study).** Fits gene-wise linear models, then shrinks per-gene variance estimates toward a global prior:

$$\tilde s_g^2 = \frac{d_0 s_0^2 + d_g s_g^2}{d_0 + d_g}.$$

The moderated t-statistic uses $\tilde s_g$ in the denominator. This borrows strength across genes — small studies benefit massively because raw $s_g^2$ is unstable with few replicates.

**MetaDE / metaRNASeq.** Implement multiple meta-analysis strategies on top of limma/edgeR/DESeq2 outputs: Fisher and Stouffer combiners, random-effects models on log fold-changes, vote-counting. metaRNASeq specifically handles RNA-seq count data with negative-binomial models per study before combining.

**Full Bayesian hierarchical (e.g., Stan/brms).** Put priors on $\mu_g, \tau_g$, sample the posterior, report $P(\mu_g > 0 \mid \text{data})$ or credible intervals. Naturally produces shrinkage and proper uncertainty.

---

## 4. Effect-Size Meta-Analysis

All these methods operate on $(\hat\beta_{gi}, s_{gi})$ pairs, gene by gene. They use strictly more information than p-value combination because they retain effect direction and magnitude.

### Fixed-effect (inverse-variance weighting)

Assumes one true $\beta_g$ shared across studies:

$$\hat\beta_g^{\text{FE}} = \frac{\sum_i \hat\beta_{gi}/s_{gi}^2}{\sum_i 1/s_{gi}^2}, \quad \text{SE} = \left(\sum_i 1/s_{gi}^2\right)^{-1/2}.$$

Test $\hat\beta_g^{\text{FE}} / \text{SE}$ against $\mathcal{N}(0,1)$. Optimal when studies measure the same effect; underestimates uncertainty under heterogeneity.

### DerSimonian–Laird random effects

Allows $\beta_{gi} \sim \mathcal{N}(\mu_g, \tau_g^2)$. Estimate $\tau_g^2$ from observed between-study variance (method of moments), then weight by $1/(s_{gi}^2 + \hat\tau_g^2)$:

$$\hat\mu_g^{\text{RE}} = \frac{\sum_i \hat\beta_{gi}/(s_{gi}^2 + \hat\tau_g^2)}{\sum_i 1/(s_{gi}^2 + \hat\tau_g^2)}.$$

### REML random effects

Same model, $\tau_g^2$ estimated by restricted maximum likelihood. More accurate than DL when $K$ is small (typical in genomics meta-analyses with 3–10 studies). `metafor::rma(..., method="REML")`.

### Hartung–Knapp–Sidik–Jonkman (HKSJ)

A correction to random-effects inference using a $t$-distribution with adjusted variance instead of normal. Substantially better coverage when $K$ is small; strongly recommended for $K < 10$.

### Hunter–Schmidt

Sample-size weighting rather than inverse-variance. Used in some fields but inverse-variance is generally preferred for genomics.

**Practical pipeline.** Per gene: feed $(\hat\beta_{gi}, s_{gi})$ into `metafor::rma` with `method="REML"` and `test="knha"`, extract the meta p-value, then apply BH across genes. This is roughly the gold standard when effect sizes are available.

---

## On Weighting and the Limits of Math

A natural worry is that information from each study should flow into the meta-analysis in a principled way, with appropriate weights reflecting study quality and relevance. Here the math gives a partial answer.

### Where math gives optimal weights for free

When studies are **commensurable** — same effect, same scale, just different precisions — there is a genuinely optimal weighting. Under the fixed-effect model $\hat\beta_i \sim \mathcal{N}(\beta, s_i^2)$, the **inverse-variance weights** $w_i = 1/s_i^2$ minimize the variance of $\hat\beta^{\text{meta}}$ among all unbiased linear combinations (Gauss–Markov), and are the MLE.

For Stouffer with one-sided z-scores, $w_i \propto \sqrt{n_i^{\text{eff}}}$ is optimal under a shared alternative.

Under random effects $\beta_i \sim \mathcal{N}(\mu, \tau^2)$, the optimal weights become $w_i = 1/(s_i^2 + \tau^2)$. As $\tau^2$ grows (more between-study disagreement), weights flatten toward equal — the math automatically tells you to stop trusting the precise studies as much when they disagree with everyone else.

### Where math runs out

There is no fully principled mathematical framework for weighting **non-commensurable** studies. Math gives nothing automatic about:

- Different cell lines, tissues, or model systems
- Variable batch correction quality
- Different time points or experimental conditions
- Replication status
- Author/lab reliability
- Different platforms (microarray vs. bulk RNA-seq vs. single-cell pseudobulk)

This is fundamental: weights answer "how much should this estimate inform my belief about $\beta$?" Sample size and standard errors capture statistical precision *conditional on the model being right*. They cannot capture model misspecification, relevance to the meta-analytic target, or trustworthiness. Those require domain knowledge — judgment.

Partial mathematical responses exist (random effects, quality-effects models, informative priors, meta-regression), but each smuggles in a judgment somewhere. **Sensitivity analysis** (leave-one-out, comparing fixed vs. random effects) is the honest empirical move: it tells you whether the weighting question matters for your conclusion. Often it doesn't.

### Equal-weighting in practice

A practical caveat: the standard pipeline of Fisher / CCT / HMP + BH effectively weights studies equally (or, for heavy-tailed combiners like CCT/HMP, lets the most extreme study dominate). Specifically:

- **Fisher**: all studies equal, no weight parameter.
- **Stouffer**: equal *only if* you choose $w_i = 1$; with $w_i = \sqrt{n_i}$ you get sample-size-weighted Stouffer, the closest p-value-only analog to inverse-variance meta-analysis.
- **CCT and HMP**: nominally equal coefficients, but heavy-tailed sums are dominated by the most extreme term, so they effectively concentrate on the strongest single study.

If sample sizes vary substantially across studies, vanilla Fisher is statistically suboptimal. Sample-size-weighted Stouffer is preferable when only p-values are available; effect-size meta-analysis is preferable when $(\hat\beta, s)$ are available.

---

## The Censoring Problem

A serious practical issue arises when studies report only p-values below some cutoff (e.g., $p < 0.05$) in their supplementary tables. This is right-censoring of p-values, and it interacts badly with the standard combiners.

### Why Stouffer is especially sensitive

The transformation $z_i = \Phi^{-1}(1 - p_i)$ is highly nonlinear near $p = 1$. Imputing missing p-values introduces strong distortion regardless of choice:

- **Impute $p = 1$**: $z = -\infty$, breaks the sum.
- **Impute $p = 0.5$**: $z = 0$, claims the gene has exactly null-median evidence — informative, not neutral.
- **Impute $p = $ cutoff**: biases everything toward significance.
- **Impute uniformly on $[0.05, 1]$**: adds noise and gives $z \approx -0.063$ on average.

Stouffer averages the evidence, so missing values cannot simply be omitted (omitting changes the denominator $\sqrt{\sum w_i^2}$). Fisher has the same issue with $\ln p_i$ blowing up near $p=1$.

CCT and HMP are dominated by the smallest p-values *by design*. Censoring the high-p tail barely affects the combined statistic because those terms contribute negligibly anyway. This is why the top of empirical rankings tends to be robust to the censoring while Stouffer is not.

### Why top-ranked genes are typically preserved

Truly strong hits have small p-values in every study where they're real. Their meta-statistic is dominated by those small p-values regardless of combiner. The censoring distorts the *middle and bottom* of the ranking — genes with marginal evidence in some studies and missing in others. For top hits, you're effectively running a CCT/HMP-like procedure regardless of nominal combiner choice.

### Options for handling censoring

**Use CCT or HMP as the primary combiner.** Robust to right-censoring by construction, robust to dependence (no independence assumption), and the combined statistic is dominated by the strongest signal — which is what survives the censoring anyway. This is probably the right default for censored p-value data.

**Truncated Product Method (Zaykin).** Explicitly designed for the case of combining only p-values below a cutoff $\tau$:

$$W = \prod_{i: p_i \le \tau} p_i.$$

The null distribution of $W$ is derived analytically accounting for the truncation. Underused in genomics but the right tool for this scenario. Rank-truncated and weighted variants exist.

**Multiple imputation.** Impute $p_i \sim \text{Uniform}(0.05, 1)$ multiple times, run meta-analysis on each, pool results. Honest about uncertainty but adds noise.

**Rank aggregation** (rank product, Robust Rank Aggregation). Ignores p-values entirely and combines per-study rankings. Totally robust to right-censoring of p-values and competitive with p-value combination at the top of the list.

**Vote counting.** Crude but honest: count how many studies report each gene as significant. Useful as a sanity check.

### Recommended practical strategy

For meta-analysis of differential expression studies with right-censored p-values, the following combination is defensible:

1. **CCT or HMP as the primary combiner** for inference robust to dependence and censoring.
2. **Rank product / RRA as a cross-check** for cross-study consistency.
3. **BH correction** applied to the meta p-values at the end.

Genes ranked highly by both CCT/HMP and rank aggregation are the most defensible discoveries: strong individual evidence *and* cross-study consistency. This dual approach also implicitly addresses the weighting problem — rather than committing to a single combiner with implicit weights, you triangulate.

---

## Summary Recommendations

1. **If effect sizes $(\hat\beta, s)$ are available across studies**, use random-effects meta-analysis on effect sizes (REML + HKSJ via `metafor`), then BH across genes. This dominates p-value combination.

2. **If only p-values are available and uncensored**, use Stouffer with $\sqrt{n}$ weights for the closest p-value-only analog to inverse-variance meta-analysis, or local FDR combination for the most principled use of per-study FDR-style information.

3. **If p-values are right-censored** (only reported below a cutoff), use CCT or HMP, the truncated product method, or rank aggregation. Avoid Stouffer and Fisher in this regime.

4. **Always report sensitivity analysis** — fixed-effect vs. random-effects vs. leave-one-out. If conclusions are stable, the weighting question didn't matter. If they aren't, you've learned something important about the dependence of your results on judgment calls, and you should make those judgments explicit.

5. **Re-derive FDR control at the meta level**, not by combining per-study FDR values. Per-study FDRs are summaries of per-study evidence; the underlying evidence flows into the meta-analysis, and FDR control is reapplied on the larger information set.

The deeper conceptual point: there is no rigorous way to combine FDR values directly because q-values are tail expectations rather than pointwise posteriors. Local FDRs, which *are* pointwise posteriors, can be combined via Bayes' rule. For most practical purposes, however, the right move is to combine the underlying evidence (effect sizes preferred, p-values otherwise) and re-derive error control on the meta-level discovery set.
