- when user selects a target gene or perturbed gene while the other is already
  selected; if the perturbed-target combination exists anywhere in the DB, don't
  redirect to searching ONLY for the clicked gene, instead search for the
  COMBINATION of the currently selected other direction + the clicked gene

- fix preprocessing/test_pipeline.py test case

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
