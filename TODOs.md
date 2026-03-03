- explainer page:
  - your explainers of the methods that you put into the report for me are really excellent. We want to include basically the full report that you wrote for me in the explainer page.
  - Please go back again to external web sources to verify that your explanations are correct. It's quite important that they are correct.
  - in the explainer, you wrote we do not use the landau-bound adjustment, but in the brief methods explainers on the combined p-values page, you mention it, why?

- in the report, you wrote that our implementations work well for "larger" p-values. Is there a way to make them robust, and identical to the R implementations, even for smaller p-values? Consider if scipy or other libraries support decimal numbers with arbitrary precision. Regarding the Landau adjustment, is there a way to implement that as well? We really want ideally identical results to the R implementations even for small p-values.

- add support for tables that have multiple p-values per row

- ASD organoid DE results missing from changelog. Is this simply duplicated from the Geschwind CNV dataset? If yes, remove; otherwise treat as a first class citizen

- copy missing datasets from /hive/groups/SSPsyGene/sspsygene_website/data/datasets or /hive/groups/SSPsyGene/sspsygene_website_int/data/datasets to local machine

- The Cauchy FDR is always the same value. Is this intentional? Seems like it's 1.032e-13 across the board. Seems implausible. Is this due to errors with floating point processing or very small numbers? Have a hard look at the implementation, identify the errors, fix them, and make sure similar errors don't apply to other p-value computations as well, and run an extensive appropriate test suite

- once all the other stuff is done:
  - the B-H corrected versions of the p-values are pretty much the same sorting as for the p-values. Consider removing these columns --- they're more distracting than anything else.
