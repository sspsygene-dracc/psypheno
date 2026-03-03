- make sure harmonic mean and CCT are well implemented for p-value combinations ---
  somehow find packages implementing these and compare, or find reference
  implementations online
- make entries in p-value tables links to gene search page
- verify Benjamini-Hochberg implementation is correct --- again somehow find packages
  implementing these and compare, or find reference implementations online
- include citations to the methods in the method descriptions incl DOI link if
  available (Fisher's is probably too old)
- include TOC in combined p-values page as well; order alphabetically
- allow further filter of genes that don't have HGNC annotation
- allow further filtering of pseudogenes

- allow no-index option in load-db to speed up loading for test purposes, omitting creating sqlite3 indices

- verify method descriptions --- https://github.com/pbagos/metacp
- see also https://pmc.ncbi.nlm.nih.gov/articles/PMC12527540/

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
