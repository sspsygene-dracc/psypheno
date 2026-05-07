# Candidate studies for psypheno ingestion

This memo lists studies (2017 and later) that produce per-gene readouts in
neuropsychiatric or neurodevelopmental contexts and that are not yet on
https://psypheno.gi.ucsc.edu nor already in flight as open tickets on
`sspsygene-dracc/psypheno`. bioRxiv-only preprints have been deferred (a short
watch-list is at the end).

---

## Tier 1 — Per-disorder gene tables (rare-variant exome and GWAS)

The data tables our website is most designed to ingest are TADA-style
per-gene Q-value / FDR / posterior-probability tables, and per-gene MAGMA
/ TWAS / fine-mapping tables from GWAS. The big ASD / NDD / SCZ / BD /
ADHD / MDD / OCD consortia produce exactly that, and several of the
canonical papers are not yet on the site.

### 1. Satterstrom 2020 — 102 ASD genes (TADA, ASC + SPARK + DDD)
- *Cell* **180**, 568–584 (2020). PMID 31981491 / doi:10.1016/j.cell.2019.12.036.
- **Per-gene fit:** Suppl. Table S2 = TADA per-gene Q-values, dnLoF /
  dnMis / inherited counts, ASD/DDD-predominance class for ~26K genes.
  Drop-in to a single dataset table.
- **Why:** This *is* the modern ASD gene list. Cited 3000+; the SFARI
  Gene high-confidence tier is downstream of it. The site currently
  surfaces SFARI Gene 2010 only — Satterstrom is what wranglers and PIs
  reach for.
- **Caveats:** Rolland 2023 (`genetrek-pasteur-fr`) already integrates
  Satterstrom Q-values into its meta-list, but the original per-gene
  table is not surfaced as its own dataset. Worth a standalone config
  for direct citation/comparison.

### 2. Fu 2022 — SPARK / iWES + ASC + DDD joint analysis
- *Nat Genet* **54**, 1320–1331 (2022). PMID 35982160 / doi:10.1038/s41588-022-01104-0.
- **Per-gene fit:** Suppl. Table 11 = TADA-NDD per-gene posteriors,
  ASD/DD-predominance class (the AUTISMp / DDp / AUTISM|DD codes our
  GeneTrek loader currently *interprets* but does not ingest as a
  primary table).
- **Why:** Successor to Satterstrom; current state of the art on ASD
  gene discovery. Surfacing the underlying per-gene posteriors directly
  would make the GeneTrek classification codes self-explanatory.
- **Caveats:** Heavy overlap with Satterstrom — needs careful
  short_label / fieldLabel work to keep them distinguishable.

### 3. Zhou 2022 — moderate-risk ASD genes (42K cases)
- *Nat Genet* **54**, 1305–1319 (2022). PMID 35982159 / doi:10.1038/s41588-022-01148-2.
- **Per-gene fit:** TADA-style per-gene exome-wide significance (60
  genes at P<2.5×10⁻⁶, 5 new: NAV3, ITSN1, MARK2, SCAF1, HNRNPUL2).
  Direct schema fit alongside Satterstrom 2020 and Fu 2022.
- **Why:** Largest combined de novo + inherited ASD gene discovery to
  date; complements rather than replaces the de-novo-focused Satterstrom
  2020. The "moderate-risk" tier (NAV3 / ITSN1 / SCAF1 / HNRNPUL2) is
  novel signal not in Satterstrom or Fu and is being heavily cited
  going forward.

### 4. Singh 2022 — SCHEMA SCZ rare-variant exome (24K cases)
- *Nature* **604**, 509–516 (2022). PMID 35396579 / doi:10.1038/s41586-022-04556-w.
- **Per-gene fit:** Suppl. Table 5 = per-gene URV burden P, Q, OR for
  ~25K genes; 10 exome-wide-significant genes (SETD1A, CUL1, XPO7,
  TRIO, CACNA1G, SP4, GRIA3, GRIN2A, HERC1, RB1CC1).
- **Why:** Direct analogue of Satterstrom for schizophrenia. Five
  SCHEMA top-10 genes (SETD1A, GRIN2A, GRIA3, TRIO, RB1CC1) overlap the
  SSPsyGene 250 list; XPO7 already has its own ticket (#62). The
  browser would let users compare ASD vs SCZ rare-variant signals
  side-by-side per gene.
- **Caveats:** Suppl tables are well-organised Excel; no access friction.

### 5. Trubetskoy 2022 — PGC SCZ3 GWAS + 287 prioritised genes
- *Nature* **604**, 502–508 (2022). PMID 35396580 / doi:10.1038/s41586-022-04434-5.
- **Per-gene fit:** Suppl. Table 12 = 287 fine-mapped/prioritised SCZ
  genes with TWAS Z, SMR, fine-mapping evidence per gene. Suppl. Table
  11 = locus-level. Paired with Singh 2022 (rare) it gives full common
  + rare SCZ per-gene coverage.
- **Why:** Single most-cited modern SCZ paper (4000+ citations).
- **Caveats:** Fine-mapping pipeline produces multiple confidence tiers;
  pick a single primary score column and document the rest as
  fieldLabels.

### 6. O'Connell 2025 — PGC bipolar update (~158K cases)
- *Nature* **639**, 968–975 (2025). PMID 39843750 / doi:10.1038/s41586-024-08468-9.
- **Per-gene fit:** 298 GWS loci → 36 mapped genes; per-gene MAGMA /
  fine-mapping / cell-type-enrichment tables. Direct successor to
  Mullins 2021 (next entry).
- **Why:** Largest BD GWAS to date (≥4× Mullins 2021). Bipolar is
  presently absent from the site (one of the three core SSPsyGene
  disease axes). When ingesting BD coverage, prefer this over Mullins;
  bundle them as we did for Gandal 2018 + 2022 (#56) if both are wanted.

### 7. Mullins 2021 — PGC bipolar GWAS (40K cases)
- *Nat Genet* **53**, 817–829 (2021). PMID 34002096 / doi:10.1038/s41588-021-00857-4.
- **Per-gene fit:** Suppl. Table 4 = 64 GWS loci → mapped genes;
  TWAS/MAGMA per-gene results in Suppl. Tables 5–6. Bipolar I vs II
  subtype split also per-gene.
- **Why:** Predecessor to O'Connell 2025; useful as a bundled companion
  rather than a standalone entry now that O'Connell is out.

### 8. Demontis 2023 — ADHD GWAS (38K cases)
- *Nat Genet* **55**, 198–208 (2023). PMID 36702997 / doi:10.1038/s41588-022-01285-8.
- **Per-gene fit:** Suppl. Tables 7–9 = MAGMA, TWAS, fine-mapping
  per-gene. Successor to Demontis 2019 (PMID 30478444).
- **Why:** ADHD is the second axis missing from the site. ADHD ↔ ASD
  comorbidity (~30%) — having both lets users do real cross-disorder
  comparisons.

### 9. Howard 2019 / Als 2023 — depression GWAS
- Howard 2019 *Nat Neurosci* **22**, 343–352. PMID 30718901.
- Als 2023 *Nat Med* **29**, 1832–1844. PMID 37464041 (1.3M cases).
- **Per-gene fit:** Both have per-gene MAGMA/TWAS in supps. Als 2023 is
  the larger, more recent paper and is the one most likely to be cited
  going forward.
- **Why:** Depression is the third "core" psychiatric axis; missing.
- **Caveats:** Als 2023 includes UK Biobank — check redistribution
  terms (the GWAS summary stats themselves are usually fine; the
  individual-level data is not what we ingest anyway).

### 10. Strom 2025 — OCD GWAS (53K cases)
- *Nat Genet* **57**, 1389–1401 (2025). PMID 40360802 / doi:10.1038/s41588-025-02189-z.
- **Per-gene fit:** 30 GWS loci → 249 candidate effector genes (25
  high-confidence: WDR6, DALRD3, CTNND1 + MHC genes). Per-gene MAGMA /
  fine-mapping. Cell-type enrichment for excitatory / D1 / D2 medium-spiny
  neurons.
- **Why:** First well-powered OCD GWAS; OCD is a fourth currently-absent
  disease axis (BD, ADHD, MDD, OCD). Pairs with Cross-Disorder PGC 2019
  for cross-disorder framing.
- **Caveats:** OCD is part of the broader anxiety / compulsive spectrum
  that is relatively under-represented in the SSPsyGene 250 — relevance
  to that gene list is weaker than ASD/SCZ.

### 11. Cross-Disorder Group of the PGC 2019 — pleiotropy across 8 disorders
- *Cell* **179**, 1469–1482 (2019). PMID 31835028 / doi:10.1016/j.cell.2019.11.020.
- **Per-gene fit:** Suppl. Tables include cross-disorder MAGMA per gene
  with disorder-specific Z-scores (ASD, ADHD, AN, BIP, MDD, OCD, SCZ,
  TS).
- **Why:** Single most useful pleiotropy reference table for our
  cross-disorder framing. Naturally pairs with the per-disorder GWAS
  papers above.

### 12. Antaki 2022 — rare CNVs in ASD (~15K trios)
- *Nat Genet* **54**, 1284–1292 (2022). PMID 35654974 / doi:10.1038/s41588-022-01064-5.
- **Per-gene fit:** CNV-level supps with per-region/per-gene burden;
  augments Satterstrom-style SNV burden with copy-number signal.
- **Why:** Largest open-data CNV ASD paper.
- **Caveats:** CNV burden data is not pure per-gene — needs careful
  schema mapping ("genes intersected by CNV X").

### 13. Wright 2023 — DDD genomic diagnosis (~13K probands)
- *N Engl J Med* **388**, 1559–1571 (2023). PMID 37043637 / doi:10.1056/NEJMoa2209046.
- **Per-gene fit:** Updates Kaplanis 2020 with additional trios +
  reanalysis; 60 new DD genes called. Per-gene diagnostic yield + de
  novo burden per gene.
- **Why:** Successor to Kaplanis 2020 in the DDD series. Substantial
  overlap with ASD genes — would let users see "ASD-only", "DD-only",
  and "both" signals side-by-side.

### 14. Kaplanis 2020 — DDD trio analysis (~31K trios)
- *Nature* **586**, 757–762 (2020). PMID 33057194 / doi:10.1038/s41586-020-2832-5.
- **Per-gene fit:** Per-gene de novo burden, significance, novel disease
  genes (285 reported significant).
- **Why:** Predecessor to Wright 2023; useful as a bundled companion.

---

## Tier 2 — Single-cell brain atlases (per gene × cell type)

Large reference atlases that produce per-gene marker / DEG lists per
cell type. They mesh well with our `wamsley-postmortem-asd` schema
(cell-type marker tables) and with the volcano-plot UI.

### 15. Velmeshev 2019 — first ASD postmortem cortex scRNA-seq
- *Science* **364**, 685–689 (2019). PMID 31097668 / doi:10.1126/science.aav8130.
- **Per-gene fit:** Suppl Table S4 = ~5K ASD-vs-CTL DEGs per cell type
  with FC and p. Drop-in.
- **Why:** Direct comparator to Wamsley 2024 (`wamsley-postmortem-asd`).
  Cited 1500+. The cleanest way to test whether the new Wamsley findings
  replicate. Notably, the Wamsley DEG list itself is gated on
  PsychENCODE Synapse (DUC); Velmeshev's is fully open in the Suppl
  Tables.
- **Caveats:** Cell-type label vocabulary differs from Wamsley — needs
  a small reconciliation table, not a blocker.

### 16. Velmeshev 2023 — human cortical development scRNA-seq atlas
- *Science* **382**, eadf0834 (2023). PMID 37824647 / doi:10.1126/science.adf0834.
- **Per-gene fit:** Per-cell-type developmental-trajectory DEGs across
  fetal → adult cortex. Pairs naturally with the prenatal-cortex
  reference atlases below.
- **Why:** Reference for "when in development is gene X expressed?"
  questions — direct fit for SSPsyGene's developmental-window framing.

### 17. Polioudakis 2019 — fetal cortex scRNA-seq (Geschwind lab)
- *Neuron* **103**, 785–801 (2019). PMID 31303374 / doi:10.1016/j.neuron.2019.06.011.
- **Per-gene fit:** Per-cell-type marker tables for fetal cortex cell
  types (ExN, IPC, vRG, oRG, etc.). Cited 1000+.

### 18. Bhaduri 2020 — cortical organoid stress signature
- *Nature* **578**, 142–148 (2020). PMID 31996853 / doi:10.1038/s41586-020-1962-0.
- **Title:** "Cell stress in cortical organoids impairs molecular
  subtype specification."
- **Per-gene fit:** Per-cell-type expression including a published
  glycolysis/ER-stress signature gene set; the headline result is the
  diff between organoid and primary fetal cells, not a marker atlas
  per se.
- **Why:** Cited 600+; widely used as the "are my organoid cells
  actually neurons?" reference. The framing is *quality control* more
  than ASD-gene-discovery.
- **Caveats:** Likely partial overlap with `brain_organoid_atlas` (Wang
  2025 *Cell Stem Cell*). Confirm scope before ingesting both.

### 19. Kanton 2019 — organoid scRNA-seq evolution
- *Nature* **574**, 418–422 (2019). PMID 31619793 / doi:10.1038/s41586-019-1654-9.
- **Per-gene fit:** Cross-species (human / chimp / macaque) organoid
  per-gene-per-cell-type DEG tables.
- **Why:** Evolutionary lens that pairs naturally with the ASD-gene
  acceleration / brain-evolution literature.

### 20. Mathys 2023 — Alzheimer's prefrontal cortex scRNA-seq (2.3M nuclei)
- *Cell* **186**, 4365–4385 (2023). PMID 37774677 / doi:10.1016/j.cell.2023.08.039.
- **Per-gene fit:** Suppl Tables = per-cell-type AD-vs-CTL DEGs.
- **Why:** Ostensibly Alzheimer's, but ~50 SSPsyGene genes overlap the
  AD risk gene list and several core SCZ genes show AD-relevant
  expression patterns. A comparator dataset.
- **Caveats:** Outside the strict neuropsych / neurodev scope —
  borderline. Lower priority unless the wrangler team wants the
  cross-disorder framing.

### 21. BICCN 2021 — primary motor cortex multi-omic atlas
- *Nature* **598**, 86–102 (2021). PMID 34616075. Capstone "multimodal
  cell census and atlas of the mammalian primary motor cortex."
- **Per-gene fit:** BICCN reference cell-type taxonomy + marker tables
  across human / macaque / marmoset / mouse motor cortex.
- **Why:** This is the cell-type ground truth that the field uses.
  Useful as a per-gene "which cell types express this?" reference.

### 22. Yao 2021 — mouse primary motor cortex multi-omic atlas
- *Nature* **598**, 103–110 (2021). PMID 34616066 / doi:10.1038/s41586-021-03500-8.
- **Per-gene fit:** Per-cell-type marker tables (transcriptomic +
  epigenomic) at deeper resolution than the cross-species BICCN
  capstone (entry 21), since it focuses on mouse only.
- **Why:** Companion to entry 21 and a natural pair for the mouse-cohort
  datasets already in our DB (`mouse-cortex-perturb-4tf`,
  `mouse-perturb-4tf`).

### 23. Siletti 2023 — adult human brain cell atlas (3M cells)
- *Science* **382**, eadd7046 (2023). PMID 37824663 / doi:10.1126/science.add7046.
- **Per-gene fit:** Per-region per-cell-type marker tables; the largest
  current reference for adult human brain.
- **Why:** Companion to Velmeshev 2023 (developmental) — together they
  span fetal → adult.

---

## Tier 3 — Cell-type GWAS enrichment (per-gene cell-type linkage)

These papers tie GWAS-prioritised genes to specific cell types. Output
is a per-gene × cell-type score matrix — direct fit.

### 24. Skene 2018 — brain cell types underlying schizophrenia
- *Nat Genet* **50**, 825–833 (2018). PMID 29785013 / doi:10.1038/s41588-018-0129-5.
- **Per-gene fit:** Per-gene EWCE specificity scores per cell type.
- **Why:** First and most-cited "which cell types matter for SCZ?"
  paper. Enables the question "does my gene's cell-type specificity
  predict its disease relevance?"

### 25. Finucane 2018 — LDSC-SEG per-tissue heritability
- *Nat Genet* **50**, 621–629 (2018). PMID 29632380 / doi:10.1038/s41588-018-0081-4.
- **Per-gene fit:** Per-tissue / per-cell-type LD-score-regression
  heritability enrichment across 53 GTEx tissues + 152 cell types.
  Per-gene "specifically expressed gene" (SEG) sets are also released
  and are the primary input for downstream LDSC-SEG runs.
- **Why:** Heavily cited (1500+) and complementary to Skene 2018 EWCE
  and Bryois 2020. Most cell-type-GWAS papers run both methods; we
  should ingest both reference resources.

### 26. Bryois 2020 — cross-disorder cell-type enrichment
- *Nat Genet* **52**, 482–493 (2020). PMID 32341526 / doi:10.1038/s41588-020-0610-9.
- **Per-gene fit:** Per-gene cell-type specificity for ASD, ADHD, AN,
  BIP, MDD, OCD, SCZ, TS, alcohol dependence.
- **Why:** Cross-disorder generalisation of Skene. Pairs naturally with
  Cross-Disorder PGC 2019 (entry 11).

### 27. Bryois 2022 — eight-cell-type brain cis-eQTLs
- *Nat Neurosci* **25**, 1104–1112 (2022). PMID 35915177 / doi:10.1038/s41593-022-01128-z.
- **Per-gene fit:** Per-gene cis-eQTL summary stats in 8 brain cell
  types (ExN, InN, AST, MGL, OLI, OPC, END, PER); GWAS colocalisation
  tables for ASD, SCZ, BIP, MDD, AD, PD.
- **Why:** Cleaner "Bryois cell-type" reference than the single-cell
  PsychENCODE 2 papers — fewer donors but more direct cell-type-resolved
  per-gene effect sizes.

### 28. Luo 2024 — brain proteome QTLs implicating psychiatric disorders
- *Mol Psychiatry* **29**, 3330–3343 (2024). PMID 38724566 / doi:10.1038/s41380-024-02576-8.
- **Per-gene fit:** Per-gene cis-pQTL summary stats from 268 postmortem
  brains (198 CTL, 45 SCZ, 25 BIP); 788 cis-pQTLs covering 883 proteins
  at FDR < 5%. Per-gene Mendelian-randomisation tests against psychiatric
  GWAS in the supplementary tables.
- **Why:** Proteome-level analogue of TWAS that is largely missing from
  psychiatric resources. Pairs naturally with the Singh 2022 / Trubetskoy
  2022 / Mullins 2021 GWAS papers above.
- **Caveats:** Cohort overlaps the BrainGVEX / CommonMind donors used
  by Wang 2018 PsychENCODE — pQTLs are independent of mRNA-level QTLs
  but the donor pool is not.

---

## Tier 4 — PsychENCODE bulk and earlier postmortem RNA-seq

The PsychENCODE 1.0 bulk papers are the foundation for much of the
modern psychiatric genomics literature. We have PsychENCODE 2 (Emani
2024 = `psychscreen`); the 2018 bulk papers are still missing.

### 29. Wang 2018 — PsychENCODE adult brain (Capstone)
- *Science* **362**, eaat8464 (2018). PMID 30545857 / doi:10.1126/science.aat8464.
- **Per-gene fit:** Per-gene TWAS Z, eQTL, isoform Q across SCZ / BPD /
  ASD. Module memberships per gene.
- **Why:** *The* PsychENCODE paper. Cited 1500+. The 2024 PsychENCODE
  2.0 papers cite it as their baseline.
- **Caveats:** Big paper, multi-table — would likely need several of
  our `data_tables` rows (eQTL, TWAS, isoform-QTL, modules).

### 30. Li 2018 — PsychENCODE developmental cortex
- *Science* **362**, eaat7615 (2018). PMID 30545854 / doi:10.1126/science.aat7615.
- **Title:** "Integrative functional genomic analysis of human brain
  development and neuropsychiatric risks."
- **Per-gene fit:** Per-gene developmental-trajectory expression /
  enrichment.
- **Why:** Companion to Wang 2018; ~1000+ citations on its own.

### 31. Amiri 2018 — PsychENCODE organoid transcriptome / epigenome
- *Science* **362**, eaat6720 (2018). PMID 30545853 / doi:10.1126/science.aat6720.
- **Title:** "Transcriptome and epigenome landscape of human cortical
  development modeled in organoids."
- **Per-gene fit:** Per-gene developmental-trajectory expression in
  hPSC-derived cortical organoids, paired with CTL fetal cortex from Li
  2018.
- **Why:** The only PsychENCODE 1.0 paper with primary organoid data,
  useful as the validation reference for downstream organoid datasets
  (`brain_organoid_atlas`, Wamsley, Bhaduri).

### 32. Wen 2024 — PsychENCODE 2 cross-ancestry developmental brain atlas
- *Science* **384**, eadh0829 (2024). PMID 38781368 / doi:10.1126/science.adh0829.
- **Per-gene fit:** Per-gene / per-isoform / per-splice-event expression
  QTLs across the developing brain in EUR + AFR ancestry. Companion to
  Emani 2024 (already loaded as `psychscreen`) but covers *developmental*
  rather than adult brain.
- **Why:** Fills the developmental-brain gap that `psychscreen` (adult)
  leaves open. Pairs naturally with Werling 2020 and Li 2018.
- **Caveats:** Heavy overlap with `psychscreen` schema — should be
  loaded as a sibling dataset, not a replacement.

### 33. Werling 2020 — early prenatal cortex WGS + RNA
- *Cell Reports* **31**, 107489 (2020). PMID 32268104 / doi:10.1016/j.celrep.2020.03.053.
- **Title:** "Whole-Genome and RNA Sequencing Reveal Variation and
  Transcriptomic Coordination in the Developing Human Prefrontal
  Cortex."
- **Per-gene fit:** Per-gene early-prenatal expression with WGS variant
  overlay. Direct fit for "is this SSPsyGene gene expressed in early
  cortical neurogenesis?"

### 34. BrainSeq Phase II — Collado-Torres 2019
- *Neuron* **103**, 203–216 (2019). PMID 31174959 / doi:10.1016/j.neuron.2019.05.013.
- **Per-gene fit:** Per-gene SCZ vs CTL DEGs (DLPFC + hippocampus, bulk
  + sorted).
- **Why:** The "other" major postmortem SCZ DEG set besides Gandal 2018;
  Lieberman lab data.

### 35. Jaffe 2018 — DLPFC SCZ developmental + eQTLs (BrainSeq Phase 1)
- *Nat Neurosci* **21**, 1117–1125 (2018). PMID 30050107 / doi:10.1038/s41593-018-0197-y.
- **Title:** "Developmental and genetic regulation of the human cortex
  transcriptome illuminate schizophrenia pathogenesis."
- **Per-gene fit:** 237 SCZ-vs-CTL DEGs in DLPFC (replicated in an
  independent cohort), per-gene developmental-trajectory dynamics, and
  cis-eQTLs at the gene/exon/junction/transcript levels — 48% of SCZ
  GWAS risk variants associate with nearby expression. Direct fit for
  per-gene-card display.
- **Why:** LIBD's BrainSeq Phase 1; companion to Collado-Torres 2019
  (entry 34). The pair gives full DLPFC + hippocampus coverage. Cited
  ~700+. The "other" SCZ DEG set the field reaches for besides Gandal
  2018.
- **Caveats:** Cohort overlaps the LIBD samples used in Benjamin 2022
  *Nat Neurosci* (PMID 36319771, caudate-nucleus SCZ) — that paper is
  worth its own candidate entry if striatal coverage becomes a priority.

---

## Tier 5 — Functional genomics in iN / iPSC neurons

Per-gene CRISPR screen hit-tables are very clean fits for our schema.
Several of the most-cited recent iN screens are missing.

### 36. Tian 2021 — genome-wide CRISPRi/a in iPSC-neurons (Kampmann)
- *Nat Neurosci* **24**, 1020–1034 (2021). PMID 34031600 / doi:10.1038/s41593-021-00862-0.
- **Title:** "Genome-wide CRISPRi/a screens in human neurons link
  lysosomal failure to ferroptosis."
- **Per-gene fit:** Genome-wide CRISPRi/a survival hits in human iN.
- **Why:** Heavily cited Kampmann-lab paper. Companion to the open
  ticket #64 (Kampmann iNeuron RNA-seq) but is the genome-wide *screen*,
  not the per-gene KO RNA-seq. Distinct dataset; probably wants its
  own ticket.

### 37. Tian 2019 — CRISPRi platform in iPSC neurons
- *Neuron* **104**, 239–255 (2019). PMID 31422865 / doi:10.1016/j.neuron.2019.07.014.
- **Title:** "CRISPR Interference-Based Platform for Multimodal Genetic
  Screens in Human iPSC-Derived Neurons." Predecessor to Tian 2021.
- **Per-gene fit:** Per-perturbation-target × per-gene-readout signed Z
  scores. Same schema as our existing perturb-seq datasets.

### 38. Dräger 2022 — CRISPRi/a in iPSC-derived microglia
- *Nat Neurosci* **25**, 1149–1162 (2022). PMID 35953545.
- **Title:** "A CRISPRi/a platform in human iPSC-derived microglia
  uncovers regulators of disease states."
- **Per-gene fit:** Per-gene microglial-state-modifier hit tables.

### 39. Lalli 2020 — neural CRISPR screens of NDD genes
- *Genome Research* **30**, 1317–1331 (2020). PMID 32887689 / doi:10.1101/gr.262295.120.
- **Title:** "High-throughput single-cell functional elucidation of
  neurodevelopmental disease-associated genes."
- **Per-gene fit:** Per-perturbed-gene × per-readout DEG matrices for
  ~30 NDD risk genes in human NPCs. Direct schema fit; tightly scoped
  to the SSPsyGene gene list.
- **Why:** One of the few studies specifically targeting the NDD gene
  list with functional perturbations in a human model.

### 40. Replogle 2022 — genome-wide Perturb-seq (K562)
- *Cell* **185**, 2559–2575 (2022). PMID 35688146 / doi:10.1016/j.cell.2022.05.013.
- **Per-gene fit:** Per-perturbed × per-readout DEG matrix at full
  genome scale.
- **Why:** Highest-cited Perturb-seq paper to date (1500+).
- **Caveats:** K562 not neural — would be a "PPI / pathway" reference,
  not directly disease-relevant. Weight accordingly.

### 41. Joung 2023 — TF Atlas in hPSC
- *Cell* **186**, 209–229 (2023). PMID 36608654.
- **Per-gene fit:** Per-TF-overexpression × per-readout differentiation
  outcome for ~1700 TFs. Several SSPsyGene TF genes are perturbed here.

---

## Tier 6 — Chromatin accessibility / regulatory genomics

### 42. Markenscoff-Papadimitriou 2020 — fetal cortex scATAC
- *Cell* **182**, 754–769 (2020). PMID 32610082 / doi:10.1016/j.cell.2020.06.002.
- **Title:** "A Chromatin Accessibility Atlas of the Developing Human
  Telencephalon."
- **Per-gene fit:** Per-gene cell-type-specific accessibility +
  enhancer-gene linkage. Direct "is gene X regulated in cell type Y?"

### 43. Trevino 2021 — multiomic fetal cortex (scATAC + scRNA)
- *Cell* **184**, 5053–5069 (2021). PMID 34390642 / doi:10.1016/j.cell.2021.07.039.
- **Per-gene fit:** Per-gene developmental-trajectory + linked
  enhancer-peak scores.

### 44. Li YE 2023 — comparative atlas of single-cell chromatin accessibility
- *Science* **382**, eadf7044 (2023). PMID 37824643 / doi:10.1126/science.adf7044.
- **Title:** "A comparative atlas of single-cell chromatin accessibility
  in the human brain."
- **Per-gene fit:** Per-cell-type accessibility + linked-gene predictions
  across adult human brain; companion to Siletti 2023 and Velmeshev 2023
  in the same *Science* issue.
- **Why:** Allen / Ren-lab; covers chromatin where Siletti covers
  transcription. Pairs naturally with Markenscoff-Papadimitriou 2020 and
  Trevino 2021 for fetal-vs-adult chromatin accessibility coverage.

### 45. Nott 2019 — cell-type-resolved myeloid epigenome
- *Science* **366**, 1134–1139 (2019). PMID 31727856.
- **Per-gene fit:** Per-gene cell-type-specific (microglia / neuron /
  oligodendrocyte / astrocyte) epigenome features. Useful for
  microglia-disease links (SCZ C4, AD).

### 46. Deng 2024 — PsychENCODE 2 regulatory elements in developing cortex
- *Science* **384**, eadh0559 (2024). PMID 38781390 / doi:10.1126/science.adh0559.
- **Title:** "Massively parallel characterization of regulatory elements
  in the developing human cortex."
- **Per-gene fit:** Per-element MPRA activity scores + per-gene
  linked-element aggregations. Pairs with Markenscoff-Papadimitriou
  2020 and Trevino 2021.
- **Why:** The MPRA companion to the developmental-cortex atlas series.
  If we ingest entries 42 / 43, this is the validation layer.

---

## Tier 7 — Variant-level constraint and somatic-mosaicism resources

### 47. Karczewski 2020 / Chen 2024 — gnomAD constraint metrics (LOEUF, pLI)
- Karczewski 2020 *Nature* **581**, 434–443. PMID 32461654 / doi:10.1038/s41586-020-2308-7.
- Chen 2024 *Nature* — "A genomic mutational constraint map using
  variation in 76,156 human genomes." PMID 38057664.
- **Per-gene fit:** Per-gene LOEUF, pLI, mis_z, oe_lof, etc.
- **Why:** The single most-referenced per-gene constraint metric in
  psychiatric genetics. We currently have no constraint info on our
  per-gene cards — a glaring gap. Karczewski cited 6000+; Chen 2024 is
  the v4 update and is likely the better fit. Both are publicly
  redistributable.

### 48. Smith 2021 — UK Biobank brain imaging GWAS
- *Nat Neurosci* **24**, 737–745 (2021). PMID 33875891.
- **Per-gene fit:** Per-gene MAGMA enrichment for ~3K brain imaging
  phenotypes.
- **Why:** Connects gene-level signal to brain-structural phenotypes —
  a different axis from the case-control GWAS papers above.
- **Caveats:** Heavy multi-phenotype data — would need UI thinking on
  how to surface "this gene is associated with N IDPs" without swamping
  the table.

### 49. Bae 2022 — somatic mutations in 131 human brains
- *Science* **377**, 511–517 (2022). PMID 35901164 / doi:10.1126/science.abm6222.
- **Title:** "Analysis of somatic mutations in 131 human brains reveals
  aging-associated hypermutability."
- **Per-gene fit:** Per-gene somatic mutation burden across 131 brains
  (CTL + ageing + neuropsychiatric); per-gene hypermutability scores.
  Direct fit for "is this gene somatically unstable in adult brain?"
  queries.
- **Why:** Brain Somatic Mosaicism Network (BSMN) flagship paper.
  Somatic mosaicism is currently absent from the site and is a recognised
  SSPsyGene-adjacent topic. Garrison 2023 (*Sci Data*, PMID 37985666)
  describes the BSMN data deposits and would make a good companion
  reference if this lands.

---

## Tier 8 — iPSC disease models (per-gene KO transcriptomics)

These are similar in spirit to `polygenic-risk-20` and
`xpo7-ipsc-neurons` but for individual-gene KOs.

### 50. Schrode 2019 — SCZ polygenic risk in iPSC neurons
- *Nat Genet* **51**, 1475–1485 (2019). PMID 31548722 / doi:10.1038/s41588-019-0497-5.
- **Title:** "Synergistic effects of common schizophrenia risk variants."

### 51. Stern 2018 — bipolar iPSC neuron sub-populations + lithium response
- *Mol Psychiatry* **23**, 1453–1465 (2018). PMID 28242870 / doi:10.1038/mp.2016.260.
- **Per-gene fit:** Per-gene DEG tables comparing iPSC-derived
  hippocampal-lineage neurons from BD-lithium-responders vs
  non-responders vs CTL. Per-gene log-fold-change + p-value; same
  shape as our existing iPSC-neuron datasets.
- **Why:** Bipolar iPSC functional model — a clean disease-axis
  comparator alongside the SCZ iPSC entries (Schrode 2019) and ASD iPSC
  (Marchetto 2017). Cited 700+. A 2020 follow-up (Stern et al. *Biol
  Psychiatry*, PMID 31732108) on dentate-gyrus / CA3 hyperexcitability is
  a worthy alternate or complement.

### 52. Marchetto 2017 — ASD iPSC cortical neurons
- *Mol Psychiatry* **22**, 820–835 (2017). PMID 27378147.
- **Title:** "Altered proliferation and networks in neural cells derived
  from idiopathic autism."

---

## Tier 9 — Protein-protein interaction maps for ASD/SCZ genes

PPI is currently absent from our site. Open published candidates:

### 53. Pintacuda 2023 — autism-gene PPI in iPSC neurons
- *Cell Genomics* **3**, 100250 (2023). PMID 36950384 / doi:10.1016/j.xgen.2023.100250.
- **Title:** "Protein interaction studies in human induced neurons
  indicate convergent biology underlying autism spectrum disorder."
- **Per-gene fit:** Per-bait × per-prey edge table for ASD-gene baits in
  iN. Direct fit for our **link table** schema.
- **Why:** Pintacuda is also a Wamsley / Gordon collaborator — likely
  consortium-friendly to ingest. A companion preview is **Bicks 2023**
  *Cell Genom* (PMID 36950377, "Neuronal protein interaction networks in
  autism spectrum disorder") — Bicks is on the Wamsley team. Bicks 2023
  is a perspective rather than primary data and probably wants flagging
  rather than ingesting.

---

## Tier 10 — Honourable mentions / older but seminal

Pre-2017 papers worth picking up if a wrangler has spare cycles:

- **Sanders 2015** *Neuron* (PMID 26402605) — TADA combined exome ASD;
  the methodology Satterstrom 2020 builds on. The 65-gene list still
  gets cited.
- **Iossifov 2014** *Nature* (PMID 25363768) — SSC ASD de novo variants.
  Still the canonical SSC reference per-gene table.
- **Yuen 2017** *Nat Neurosci* (PMID 28263302) — WGS of ~5K MSSNG ASD
  families; per-gene candidate-gene table.
- **De Rubeis 2014** *Nature* (PMID 25363760) — TADA on ASC exome.
  Companion to Iossifov 2014 in the same issue.
- **Coe 2014** *Nat Genet* — DD CNVs.

---

## Out-of-scope but worth flagging

Things we would **not** recommend ingesting but that come up often
enough that the team should know they exist:

- **Allen Brain Cell Atlas / Yao 2023 mouse brain** — gigantic, but we
  already have Polioudakis-style human cell types covered. The mouse
  atlas is better consumed via `cellxgene` or the Allen portal.
- **Per-disorder PRS papers** — usually no per-gene readout; PRS is a
  polygenic *score*, not a per-gene quantity. Skip unless the paper also
  publishes per-gene LDSC / MAGMA.
- **GTEx** — already embedded in PsychENCODE / TWAS papers; standalone
  ingestion is more work than it's worth.
- **ENCODE candidate cis-regulatory elements (cCREs)** — not per-gene
  natively; would need an enhancer-to-gene aggregation.

### Watch-list (currently bioRxiv-only — revisit on journal publication)

- **Gschwind 2023 — ENCODE rE2G enhancer-gene links.** bioRxiv
  2023.11.09.563812 (PMID 38014075 indexes the preprint). The 25.09
  Open Targets release already pulls from the preprint; will be the canonical enhancer-gene resource for
  psychiatric GWAS variant interpretation when published. Per-enhancer-
  gene-pair score across 352 cell types; >13M E-G interactions; per-gene
  aggregated enhancer-disease GWAS overlap. Direct fit for our link-table
  schema once available.
- **Kampmann lab "Massively parallel CRISPR-based Screening Platform for
  Modifiers of Neuronal Activity"** (2024).
- **SingleBrain 2025 sn-eQTL meta-analysis** — still medRxiv-only.

---

## Suggested prioritisation for the next ticket round

Highest expected value (well-published, clean per-gene supps, clear
gap):

1. **Satterstrom 2020 + Fu 2022 ASD gene tables** (Tier 1) — pair them;
   together they replace SFARI 2010 as the primary ASD gene ranking on
   the site.
2. **Singh 2022 SCHEMA + Trubetskoy 2022 PGC SCZ3** (Tier 1) — pair
   them; gives full common+rare SCZ coverage. Direct comparator to the
   ASD pair.
3. **Karczewski 2020 / Chen 2024 gnomAD constraint** (Tier 7) — high
   utility per unit work; would surface LOEUF / pLI on every gene card.
4. **Velmeshev 2019 ASD cortex scRNA** (Tier 2) — comparator for the
   already-loaded Wamsley 2024, and the DEG list is open in Suppl while
   Wamsley's is gated.
5. **Cross-Disorder PGC 2019 + Bryois 2020 cross-disorder cell types**
   (Tier 1 + Tier 3) — pair them; activates the cross-disorder framing
   across the whole site at once.
6. **Pintacuda 2023 ASD-gene PPI** (Tier 9) — first published PPI
   dataset.
7. **O'Connell 2025 bipolar + Demontis 2023 ADHD + Als 2023 depression
   + Strom 2025 OCD** (Tier 1) — fills the four currently-absent
   disease axes.

Lower expected value but worth filing tickets so the wrangler team can
pick them up opportunistically:

- Wang 2018 / Li 2018 / Amiri 2018 PsychENCODE 1.0 bulk + organoid
  (Tier 4).
- Tian 2021 CRISPRi iN + Lalli 2020 ASD-gene CRISPR (Tier 5).
- Markenscoff-Papadimitriou 2020 / Trevino 2021 / Nott 2019 / Deng 2024
  (Tier 6).
- Polioudakis 2019 / Bhaduri 2020 / Kanton 2019 / Velmeshev 2023
  (Tier 2 — partial overlap with `brain_organoid_atlas` /
  `wamsley-postmortem-asd`; check before ingesting).
