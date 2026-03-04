IMMEDIATE:
  - the combined p-values page is not user-friendly. a couple of points:
    - in the table (but not in the Gene search Results "home" page), on mobile only, the font of the gene info box is way too large, as is the font of the methods descriptions that you can expand. (The font on the full methods documentation is fine on mobile)
    - The current table with the very many numbers in green is not user-friendly. We should make many changes:
      - the table should only have 6 columns and be much narrower:
        - gene rank
        - gene
        - currently selected p-value ranking method, in standard (sans serif) font, color coded and bold, with a range of color codes spanning the top 100 p-values; p-values outside the top 100 for the current ranking method should simply display in standard font, not bold, not color-coded
        - number of tables
        - number of p-values
        - gene info button as now
      - above the table, we should have a dropdown selector for fisher, stouffer, cauchy, hmp
      - below the dropdown selector, the brief method description + link to full doc that is currently in the dropdown; the dropdown should vanish
    - the page should be renamed "most significant genes" and most-significant.tsx; the current combined-pvalues should redirect to most-significant for backwards compatibility
    - The page title should similarly change to "Ranking the Most Significant Genes Across All Datasets"
      - below this page title, we should print a very accessible information about why we created this page, and what it's good for, for the research project, downstream analyses, understanding the data, etc. so people even know what the page is good for


LATER:
  - run more verification and new data generation agents --- skip those that we already verified in the aborted run
