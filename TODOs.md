- Bug: I still can't search for ALL control genes by entering CONTROL in the
  gene search fields. Also add that searching for CONTROL searches for ALL
  control genes (all names of control genes) across all tables. Add this info
  to the (i) tooltip for the perturbed and target genes
- Bug: After selecting target gene from suggestion dropdown in gene search box,
  the search box doesn't update its text; just 2 letters visible (the ones I
  entered manually)
- ensure changelog of all config yamls is updated properly (no ticket — just a
  reminder: many changes have landed since Monday 2026-04-27; before the sprint
  email, sweep data/datasets/*/config.yaml changelog blocks and bring them up
  to date)
- Reconsider combining +/− effect sizes in the aggregation. (Max notes;
  [GH #74])
- Improve dataset titles. (Max 3/24; [GH #79])
- Parse GENBANK accessions to genes #139
- Description of gene parser #147
- P-values problems #148
- Rename "direction" throughout the codebase from perturbed/target to something
  else; direction seems to suggest "up/downregulated", which is not what this
  refers to. Disentangle from actual up/downregulated cases (should mostly be
  in most-significant)
- Migrate zebraAsd if still necessary #156
- One separate dataset_name.preprocessing.yaml per table, not per
  preprocess.py #158
- Complete column header tooltips #160
- Cache results of R computations. By computing a hash over the actual input
  to R, and saving results, we're probably able to save a huge chunk of
  re-computation on load-db

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