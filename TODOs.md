- explainer page:
- explain that most methods return results similar to
  Fisher, which is why we omitted them; explain that other methods are robust to dependency structures between experiments;
- go a bit into the fact that methods that assume independency are almost always
  wrong, but often still canonical and useful, and explain that this is due to the
  underlying causal structure, and they probably just over-estimate the effect size
  in terms of p-value compared to the true causal effect size.
- Explain what the non-Fisher methods do and that while we can't vouch for them, at
  least they try to account for dependency structure between experiments.

- add support for tables that have multiple p-values per row

- ASD organoid DE results missing from changelog. Is this simply duplicated from the Geschwind CNV dataset? If yes, remove; otherwise treat as a first class citizen

- copy missing datasets from /hive/groups/SSPsyGene/sspsygene_website/data/datasets or /hive/groups/SSPsyGene/sspsygene_website_int/data/datasets to local machine

- The Cauchy FDR is always the same value. Is this intentional? Seems like it's 1.032e-13 across the board. Seems implausible

- the B-H corrected versions of the p-values are pretty much the same sorting as for the p-values. Consider removing these columns --- they're more distracting than anything else.
