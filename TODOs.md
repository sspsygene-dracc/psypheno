- significance summary boxes can get too wide with dataset titles --- make sure
  the dataset column wraps at some max width rather than just extending
  endlessly. Try to make it work on mobile as well. See, e.g., what happens when
  you expand the description of NR4A3 on
  http://localhost:3000/most-significant?reg=up&assay=expression&disease=asd

- on narrow mobile, just hide the What's New box on the home page --- it takes
  up too much space and doesn't add that much

- make deploy script run full test suite, incl slow tests and e2e tests, on the
  deployed paths, using a separate option (like --preprocess but for testing)

- Gordon 2026 - ASD Genetic-Form DEGs in iPSC Cortical Organoids doesn't have a
  perturbed gene column, but it should, in the GUI (e.g. on the home gene
  results page). Somehow the perturbed gene column is hidden, It should in fact
  be first according to our default ordering

- Security review #157

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
