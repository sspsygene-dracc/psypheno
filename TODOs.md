- evaluate different p-value combination methods; pick a couple that return different results;
  - create rank correlation confusion matrices, cluster and pick a couple of quite different ones;
  - create explainer page:
    - explain our methodology; explain that most methods return results similar to
      Fisher, which is why we omitted them; explain that other methods are robust to dependency structures between experiments;
    - go a bit into the fact that methods that assume independency are almost always
      wrong, but often still canonical and useful, and explain that this is due to the
      underlying causal structure, and they probably just over-estimate the effect size
      in terms of p-value compared to the true causal effect size.
    - Explain what the non-Fisher methods do and that while we can't vouch for them, at
      least they try to account for dependency structure between experiments.
