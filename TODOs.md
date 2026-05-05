- the deployment scripts should take another flag to re-run preprocessing
  optionally

- UI improvements:
  - Small feature: when scrolling over pages that have a "datasets" TOC, bold or
    otherwise highlight the currently scrolled-to item from the main area in the
    TOC
  - Bug: Gordon 2026 - ASD Genetic-Form DEGs in iPSC Cortical Organoids doesn't
    seem to have a Target Gene Resolution column, why not? All parsed genes should
    have a raw and a resolution column, please check this
  - Bug: when clicking on a perturbed gene in a perturbed gene column in various
    data tables (notably on the gene results "home" page), it still searches for
    the gene as a target gene, not as a perturbed gene
  - Bug: I still can't search for ALL control genes by entering CONTROL in the
    gene search fields. I want to be able to search for ALL controls (some kind of
    placeholder) somehow. Also add instructions for this searching for CONTROL
    searches for ALL control genes (all names of control genes) across all tables.
    Add this info to the (i) tooltip for the perturbed and target genes if not
    already there.
  - Bug: After selecting target gene from suggestion dropdown in gene search box,
    the search box doesn't update its text; just 2 letters visible (the ones I
    entered manually)

On 147 thread, do a post-pass to verify wording and correctness

- ensure changelog of all config yamls is updated properly (no ticket — just a
  reminder: many changes have landed since Monday 2026-04-27; before the sprint
  email, sweep data/datasets/*/config.yaml changelog blocks and bring them up
  to date)
- Description of gene parser #147
- One separate dataset_name.preprocessing.yaml per table, not per
  preprocess.py #158 . Make sure to thread through to downloads page
- Complete column header tooltips #160. Look up in the papers/ dir. Consider
  downloading supplementary files where necessary. Instruct me what supplements
  to download manually, and where to, if automatic download fails.

- Security review #157
- Test-suite buildout: Python backend, frontend unit, frontend e2e,
  data-correspondence spot-check (randomized verification that
  per-row + meta-analysis output matches source data). (Internal
  Colossus; [GH #117] tracker — leaves #110, #111, #112, #113)
- Test on mobile — re-evaluate after recent changes. #155

- What's new section update #127
- Wranglers update email — effect_column requirement + refreshed
  docs/adding-datasets.md; piggyback on items F.1, F.2 once they land.
  (Internal Colossus; [GH #97])
- At the end, deploy everything to _dev and _int, rerun the preprocessing and
  load-db, and make sure the website looks good and run all tests on the server
  (e2e tests on the dev instance)
- At the end, write a big update email that concisely but completely chunks
  all the features, bug fixes, and updates from my end (Colossus) into a list for
  Catharina and Max, complete with links to the website and where they can see the
  updated results. I'd also like a rough estimate on how many lines were
  added/removed for each feature, plus and overall update on how many LOC were
  added/removed overall through this sprint since Monday.
