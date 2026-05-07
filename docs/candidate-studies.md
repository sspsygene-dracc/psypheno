# Candidate studies for future ingestion

**Drafted 2026-05-07.** Working scratchpad, kept in-tree under `docs/`.

**Verification pass 1 (2026-05-07):** PMIDs and journal names below have
been spot-checked against NCBI esummary for ~40 of the 43 candidates.
Significant corrections are inline. One candidate ("Marshall 2017 ASD
CNVs", which had been drafted from recall) was dropped on verification —
Marshall CR 2017 *Nat Genet* (PMID 27869829) is actually a *schizophrenia*
CNV paper, not ASD, and no equivalent Marshall 2017 ASD CNV paper exists.

**Verification pass 2 (2026-05-07):** With WebSearch / WebFetch
restored, the five remaining `[VERIFY]` items were resolved (see the
"Verification log — pass 2" section at the bottom), seven cross-check
candidates flagged in pass 1 were folded in as a new Tier 11, and a
fresh search surfaced eight 2022–2025 papers that hadn't been on the
original recall list.

The goal: surface high-impact published studies (2017+) that produce
**per-gene** readouts in neuropsychiatric / neurodevelopmental contexts and
that are *not* already covered by an existing dataset folder or open ticket
on `sspsygene-dracc/psypheno`. A few seminal pre-2017 papers are noted at
the bottom for completeness.

For each candidate I've tried to capture:
- **Citation** + PMID/DOI.
- **Per-gene fit** — what the supplementary tables actually look like, so
  we can predict whether the data slots into our `display_columns` /
  `scalar_columns` model without major contortions.
- **Why it matters** — community visibility, citation count, overlap with
  the SSPsyGene 250-gene list, or filling a recognized gap.
- **Caveats** — overlap with existing datasets, data-access frictions,
  redaction risk, etc.

Already-loaded datasets and existing open tickets are not repeated here —
see [`dataset-backlog-report.md`](dataset-backlog-report.md) for the
in-flight reconciliation.

---

## Tier 1 — High-impact ASD / NDD rare-variant gene lists

The data tables our website is *most* designed to ingest are TADA-style
per-gene Q-value / FDR / posterior-probability tables. The big ASD/NDD
sequencing consortia produce exactly that, and several of the canonical
ones aren't yet on the site.

### 1. Satterstrom 2020 — 102 ASD genes (TADA, ASC + SPARK + DDD)
- *Cell* **180**, 568–584 (2020). PMID **31981491** /
  doi:10.1016/j.cell.2019.12.036.
- **Per-gene fit:** Suppl. Table S2 = TADA per-gene Q-values, dnLoF /
  dnMis / inherited counts, ASD/DDD-predominance class for ~26K genes.
  Drop-in to a single dataset table.
- **Why:** This *is* the modern ASD gene list. Cited 3000+; the SFARI
  Gene high-confidence tier is downstream of it. Currently we surface
  SFARI Gene 2010 only — Satterstrom is what wranglers and PIs actually
  reach for.
- **Caveats:** Rolland 2023 (`genetrek-pasteur-fr`) already integrates
  Satterstrom Q-values into its meta-list, but the original per-gene
  table is not surfaced as its own dataset. Worth a standalone config
  for direct citation/comparison.

### 2. Fu 2022 — SPARK / iWES + ASC + DDD joint analysis
- *Nat Genet* **54**, 1320–1331 (2022). PMID **35982160** /
  doi:10.1038/s41588-022-01104-0.
- **Per-gene fit:** Suppl. Table 11 = TADA-NDD per-gene posteriors,
  ASD/DD-predominance class (the AUTISMp / DDp / AUTISM|DD codes our
  GeneTrek loader currently *interprets* but doesn't ingest as a primary
  table).
- **Why:** Successor to Satterstrom, current state of the art on ASD
  gene discovery. The classification codes are already documented in
  our GeneTrek config — surfacing the underlying per-gene posteriors
  directly would make the codes self-explanatory.
- **Caveats:** Heavy overlap with Satterstrom — needs careful
  short_label / fieldLabel work to keep them distinguishable. SPARK
  iWES v1 sub-cohort codes (NCIp/CIp/NCI|CI) are still partially
  inferred — best to pair with a SPARK consortium PDF.

### 3. Singh 2022 — SCHEMA SCZ rare-variant exome (24K cases)
- *Nature* **604**, 509–516 (2022). PMID **35396579** /
  doi:10.1038/s41586-022-04556-w.
- **Per-gene fit:** Suppl. Table 5 = per-gene URV burden P, Q, OR for
  ~25K genes; 10 exome-wide-significant genes (SETD1A, CUL1,
  XPO7, TRIO, CACNA1G, SP4, GRIA3, GRIN2A, HERC1, RB1CC1).
- **Why:** Direct analogue of Satterstrom for schizophrenia. Five
  SCHEMA top-10 genes (SETD1A, GRIN2A, GRIA3, TRIO, RB1CC1) overlap
  the SSPsyGene 250 list; XPO7 already has its own ticket (#62).
  The browser would let users compare ASD vs SCZ rare-variant signals
  side-by-side per gene.
- **Caveats:** Suppl tables are well-organized Excel; no access
  friction.

### 4. Trubetskoy 2022 — PGC SCZ3 GWAS + 287 prioritized genes
- *Nature* **604**, 502–508 (2022). PMID **35396580** /
  doi:10.1038/s41586-022-04434-5.
- **Per-gene fit:** Suppl. Table 12 = 287 fine-mapped/prioritized SCZ
  genes with TWAS Z, SMR, fine-mapping evidence per gene. Suppl.
  Table 11 = locus-level. The per-gene file is the primary candidate;
  paired with Singh 2022 (rare) it gives full common+rare SCZ per-gene
  coverage.
- **Why:** Single most-cited modern SCZ paper (4000+ citations).
- **Caveats:** Fine-mapping pipeline produces multiple confidence
  tiers; pick a single primary score column and document the rest as
  fieldLabels.

### 5. Mullins 2021 — PGC bipolar GWAS (40K cases)
- *Nat Genet* **53**, 817–829 (2021). PMID **34002096** /
  doi:10.1038/s41588-021-00857-4.
- **Per-gene fit:** Suppl. Table 4 = 64 GWS loci → mapped genes;
  TWAS/MAGMA per-gene results in Suppl. Tables 5–6. Bipolar I vs II
  subtype split also per-gene.
- **Why:** Bipolar is presently absent from the site (one of the
  three core SSPsyGene disease axes). High citation count.
- **Caveats:** A 2025 PGC bipolar follow-up may exist — check before
  ingesting; if so, bundle similar to Gandal 2018+2022 (#56).

### 6. Demontis 2023 — ADHD GWAS (38K cases)
- *Nat Genet* **55**, 198–208 (2023). PMID **36702997** /
  doi:10.1038/s41588-022-01285-8.
- **Per-gene fit:** Suppl. Tables 7–9 = MAGMA, TWAS, fine-mapping
  per-gene. Successor to Demontis 2019 (PMID 30478444).
- **Why:** ADHD is the second axis missing from the site. ADHD ↔ ASD
  comorbidity (~30%) — having both lets users do real cross-disorder
  comparisons.
- **Caveats:** None obvious.

### 7. Howard 2019 / Als 2023 — depression GWAS
- Howard 2019 *Nat Neurosci* **22**, 343–352. PMID **30718901**.
- Als 2023 *Nat Med* **29**, 1832–1844. PMID **37464041** (1.3M cases).
- **Per-gene fit:** Both have per-gene MAGMA/TWAS in supps. Als 2023
  is the larger, more recent, and is the one most likely to be cited
  going forward.
- **Why:** Depression is the third "core" psychiatric axis; missing.
- **Caveats:** Als 2023 includes UK Biobank — check redistribution
  terms (the GWAS summary stats themselves are usually fine; the
  individual-level data is not what we ingest anyway).

### 8. Cross-Disorder Group of the PGC 2019 — pleiotropy across 8 disorders
- *Cell* **179**, 1469–1482 (2019). PMID **31835028** /
  doi:10.1016/j.cell.2019.11.020.
- **Per-gene fit:** Suppl. Tables include cross-disorder MAGMA per
  gene with disorder-specific Z-scores (ASD, ADHD, AN, BIP, MDD, OCD,
  SCZ, TS).
- **Why:** Single most useful pleiotropy reference table for our
  cross-disorder framing. Would naturally pair with the per-disorder
  GWAS papers above.

### 9. Antaki 2022 — rare CNVs in ASD (~15K trios)
- *Nat Genet* **54**, 1284–1292 (2022). PMID **35654974** /
  doi:10.1038/s41588-022-01064-5. ✓ verified — *Nat Genet*, not
  *Nature*; corrected PMID.
- **Per-gene fit:** CNV-level supps with per-region/per-gene burden;
  augment Satterstrom-style SNV burden with copy-number signal.
- **Why:** SSPsyGene already carries CNV-adjacent context (Geschwind
  2026 CNV folder, exists on int but no public ticket). Antaki is the
  largest open-data CNV ASD paper.
- **Caveats:** CNV burden data is not pure per-gene — needs careful
  schema mapping ("genes intersected by CNV X").

### 10. Kaplanis 2020 — Deciphering Developmental Disorders trio analysis
- *Nature* **586**, 757–762 (2020). PMID **33057194** /
  doi:10.1038/s41586-020-2832-5. ~31K trios.
- **Per-gene fit:** Suppl Tables = per-gene de novo burden,
  significance, novel disease genes (285 reported significant).
- **Why:** Largest trio analysis in NDD. Substantial overlap with
  ASD genes — would let users see "ASD-only", "DD-only", and "both"
  signals side-by-side. The follow-up Wright 2023 *Nature* extends
  this to ~36K trios; pick the more recent one if both can't be done.

---

## Tier 2 — Single-cell brain atlases (per gene × cell type)

These are large reference atlases that produce per-gene marker / DEG
lists per cell type. They mesh well with our `wamsley-postmortem-asd`
schema (cell-type marker tables) and with the volcano-plot UI.

### 11. Velmeshev 2019 — first ASD postmortem cortex scRNA-seq
- *Science* **364**, 685–689 (2019). PMID **31097668** /
  doi:10.1126/science.aav8130.
- **Per-gene fit:** Suppl Table S4 = ~5K ASD-vs-CTL DEGs per cell
  type with FC and p. Drop-in.
- **Why:** Predecessor / direct comparator to Wamsley 2024
  (`wamsley-postmortem-asd`). Cited 1500+. Including it is the
  cleanest way to test whether the new Wamsley findings replicate.
  Notably, the Wamsley DEG list itself is gated on PsychENCODE
  Synapse (DUC); Velmeshev's is fully open in the Suppl Tables.
- **Caveats:** Cell-type label vocab differs from Wamsley — needs a
  small reconciliation table, not a blocker.

### 12. Velmeshev 2023 — human cortical development scRNA-seq atlas
- *Science* **382**, eadf0834 (2023). PMID **37824647** /
  doi:10.1126/science.adf0834.
- **Per-gene fit:** Per-cell-type developmental-trajectory DEGs across
  fetal → adult cortex. Pairs naturally with the prenatal-cortex
  reference atlases below.
- **Why:** Reference for "when in development is gene X expressed?"
  questions — a direct fit for SSPsyGene's developmental-window
  framing.

### 13. Polioudakis 2019 — fetal cortex scRNA-seq (Geschwind lab)
- *Neuron* **103**, 785–801 (2019). PMID **31303374** /
  doi:10.1016/j.neuron.2019.06.011.
- **Per-gene fit:** Per-cell-type marker tables for fetal cortex
  cell types (ExN, IPC, vRG, oRG, etc.). Cited 1000+.

### 14. Bhaduri 2020 — cortical organoid stress signature
- *Nature* **578**, 142–148 (2020). PMID **31996853** /
  doi:10.1038/s41586-020-1962-0. ✓ corrected PMID.
- **Title (verified):** "Cell stress in cortical organoids impairs
  molecular subtype specification."
- **Per-gene fit:** Per-cell-type expression including a published
  glycolysis/ER-stress signature gene set; the headline result is the
  diff between organoid and primary fetal cells, not a marker atlas
  per se.
- **Why:** Cited 600+; widely used as the "are my organoid cells
  actually neurons?" reference. Worth ingesting but the framing is
  *quality control* more than ASD-gene-discovery.
- **Caveats:** Likely partial overlap with `brain_organoid_atlas`
  (Wang 2025 Cell Stem Cell). Confirm scope before ingesting both.

### 15. Kanton 2019 — organoid scRNA-seq evolution
- *Nature* **574**, 418–422 (2019). PMID **31619793** /
  doi:10.1038/s41586-019-1654-9. ✓ corrected PMID.
- **Per-gene fit:** Cross-species (human / chimp / macaque) organoid
  per-gene-per-cell-type DEG tables.
- **Why:** Evolutionary lens that pairs naturally with the ASD-gene
  acceleration / brain-evolution literature.

### 16. Mathys 2023 — Alzheimer's prefrontal cortex scRNA-seq (2.3M nuclei)
- *Cell* **186**, 4365–4385 (2023). PMID **37774677** /
  doi:10.1016/j.cell.2023.08.039.
- **Per-gene fit:** Suppl Tables = per-cell-type AD-vs-CTL DEGs.
- **Why:** Ostensibly Alzheimer's, but ~50 SSPsyGene genes overlap
  the AD risk gene list and several core SCZ genes show AD-relevant
  expression patterns. A comparator dataset.
- **Caveats:** Outside the strict neuropsych / neurodev scope —
  borderline. Lower priority unless the wrangler team wants the
  cross-disorder framing.

### 17. BICCN 2021 — primary motor cortex multi-omic atlas
- *Nature* **598**, 86–102 (2021). PMID **34616075** (the BICCN
  capstone "multimodal cell census and atlas of the mammalian primary
  motor cortex"). ✓ corrected PMID.
- **Per-gene fit:** BICCN reference cell-type taxonomy + marker
  tables across human/macaque/marmoset/mouse motor cortex.
- **Why:** This is the cell-type ground truth that the field uses.
  Useful as a per-gene "which cell types express this?" reference.
- **Note:** Companion Nature paper Yao Z 2021 (PMID **34616066**,
  "A transcriptomic and epigenomic cell atlas of the mouse primary
  motor cortex") is the mouse-only deeper analysis — possible
  separate ingestion.

### 18. Siletti 2023 — adult human brain cell atlas (3M cells)
- *Science* **382**, eadd7046 (2023). PMID **37824663** /
  doi:10.1126/science.add7046. ✓ corrected PMID.
- **Per-gene fit:** Per-region per-cell-type marker tables; the
  largest current reference for adult human brain.
- **Why:** Companion to Velmeshev 2023 (developmental) — together
  they span fetal → adult.

---

## Tier 3 — Cell-type GWAS enrichment (per-gene cell-type linkage)

These papers tie the GWAS-prioritized genes to specific cell types.
Output is a per-gene × cell-type score matrix — direct fit.

### 19. Skene 2018 — brain cell types underlying schizophrenia
- *Nat Genet* **50**, 825–833 (2018). PMID **29785013** /
  doi:10.1038/s41588-018-0129-5. ✓ corrected PMID — original PMID
  29632380 actually points to **Finucane 2018** *Nat Genet*
  ("Heritability enrichment of specifically expressed genes
  identifies disease-relevant tissues and cell types"), which is a
  separate but closely-related paper also worth considering as its
  own candidate (LDSC-SEG; per-tissue/cell-type heritability).
- **Per-gene fit:** Per-gene EWCE specificity scores per cell type.
- **Why:** First and most-cited "which cell types matter for SCZ?"
  paper. Enables the question "does my gene's cell-type specificity
  predict its disease relevance?".

### 20. Bryois 2020 — cross-disorder cell-type enrichment
- *Nat Genet* **52**, 482–493 (2020). PMID **32341526** /
  doi:10.1038/s41588-020-0610-9.
- **Per-gene fit:** Per-gene cell-type specificity for ASD, ADHD,
  AN, BIP, MDD, OCD, SCZ, TS, alcohol dependence.
- **Why:** Cross-disorder generalization of Skene. Pairs naturally
  with Cross-Disorder PGC 2019 (#8 above).

### 21. Luo 2024 — brain proteome QTLs implicating psychiatric disorders
- *Mol Psychiatry* **29**, 3330–3343 (2024). PMID **38724566** /
  doi:10.1038/s41380-024-02576-8. **Pass-2 correction:** The original
  draft credited Bryois as first author of a 2024 PWAS paper; that
  paper does not exist. Bryois J appears as a co-author here (and a
  separate Bryois et al. 2022 *Nat Neurosci* eight-cell-type cis-eQTL
  paper, PMID 35915177, is the closer "Bryois 2024" the drafter likely
  had in mind — also worth filing as its own candidate).
- **Per-gene fit:** Per-gene cis-pQTL summary stats from 268
  postmortem brains (198 CTL, 45 SCZ, 25 BIP); 788 cis-pQTLs covering
  883 proteins at FDR < 5%. Per-gene Mendelian-randomization tests
  against psychiatric GWAS in the supplementary tables.
- **Why:** Proteome-level analogue of TWAS that's largely missing
  from psychiatric resources. Pairs naturally with Singh 2022 / Trubetskoy
  2022 / Mullins 2021 GWAS papers above.
- **Caveats:** Cohort overlaps the BrainGVEX / CommonMind donors used
  by Wang 2018 PsychENCODE — pQTLs are independent of mRNA-level QTLs
  but the donor pool isn't.

---

## Tier 4 — PsychENCODE bulk + earlier postmortem RNAseq

The PsychENCODE 1.0 bulk papers are the foundation for a lot of the
modern psychiatric genomics literature. We have PsychENCODE 2 (Emani
2024 = `psychscreen`); the 2018 bulk papers are still missing.

### 22. Wang 2018 — PsychENCODE adult brain (Capstone)
- *Science* **362**, eaat8464 (2018). PMID **30545857** /
  doi:10.1126/science.aat8464.
- **Per-gene fit:** Per-gene TWAS Z, eQTL, isoform Q across SCZ /
  BPD / ASD. Module memberships per gene.
- **Why:** The "PsychENCODE paper". Cited 1500+. The 2024 PsychENCODE
  2.0 papers cite it as their baseline.
- **Caveats:** Big paper, multi-table — would likely need
  several of our `data_tables` rows (eQTL, TWAS, isoform-QTL, modules).

### 23. Li 2018 — PsychENCODE developmental cortex
- *Science* **362**, eaat7615 (2018). PMID **30545854** /
  doi:10.1126/science.aat7615. ✓ corrected PMID — title verified
  as "Integrative functional genomic analysis of human brain
  development and neuropsychiatric risks." The original PMID
  30545853 is **Amiri 2018** *Science* ("Transcriptome and epigenome
  landscape of human cortical development modeled in organoids") —
  separate PsychENCODE paper, also worth considering as its own
  candidate.
- **Per-gene fit:** Per-gene developmental-trajectory expression /
  enrichment.
- **Why:** Companion to Wang 2018; also still ~1000+ citations on its
  own.

### 24. Werling 2020 — early prenatal cortex WGS + RNA
- *Cell Reports* **31**, 107489 (2020). PMID **32268104** /
  doi:10.1016/j.celrep.2020.03.053. ✓ corrected PMID. Title
  verified: "Whole-Genome and RNA Sequencing Reveal Variation and
  Transcriptomic Coordination in the Developing Human Prefrontal
  Cortex."
- **Per-gene fit:** Per-gene early-prenatal expression with WGS
  variant overlay. Direct fit for "is this SSPsyGene gene expressed
  in early cortical neurogenesis?".

### 25. BrainSeq Phase II — Collado-Torres 2019
- *Neuron* **103**, 203–216 (2019). PMID **31174959** /
  doi:10.1016/j.neuron.2019.05.013.
- **Per-gene fit:** Per-gene SCZ vs CTL DEGs (DLPFC + hippocampus,
  bulk + sorted).
- **Why:** The "other" major postmortem SCZ DEG set besides Gandal
  2018; Lieberman lab data.

### 26. Jaffe 2018 — DLPFC SCZ developmental + eQTLs (BrainSeq Phase 1)
- *Nat Neurosci* **21**, 1117–1125 (2018). PMID **30050107** /
  doi:10.1038/s41593-018-0197-y. ✓ pass-2 verified — title
  "Developmental and genetic regulation of the human cortex
  transcriptome illuminate schizophrenia pathogenesis."
- **Per-gene fit:** 237 SCZ-vs-CTL DEGs in DLPFC (replicated in an
  independent cohort), per-gene developmental-trajectory dynamics, and
  cis-eQTLs at the gene/exon/junction/transcript levels — 48% of SCZ
  GWAS risk variants associate with nearby expression. Direct fit for
  per-gene-card display.
- **Why:** Lieberman / LIBD's BrainSeq Phase 1; companion to the
  Collado-Torres 2019 BrainSeq Phase II (#25 above) — the pair gives
  full DLPFC + hippocampus coverage. Heavily cited (~700+) and the
  "other" SCZ DEG set the field reaches for besides Gandal 2018.
- **Caveats:** Cohort overlaps the LIBD samples used in Benjamin 2022
  *Nat Neurosci* (PMID 36319771, caudate-nucleus SCZ) — that paper is
  worth its own candidate entry if the wrangler wants striatal
  coverage too.

---

## Tier 5 — Functional genomics in iN / iPSC neurons

Per-gene CRISPR screen hit-tables are very clean fits for our schema.
Several of the most-cited recent iN screens are missing.

### 27. Tian 2021 — genome-wide CRISPRi/a in iPSC-neurons (Kampmann)
- *Nat Neurosci* **24**, 1020–1034 (2021). PMID **34031600** /
  doi:10.1038/s41593-021-00862-0. ✓ corrected — was *Nat Neurosci*,
  not *Cell*; corrected PMID. Title verified: "Genome-wide CRISPRi/a
  screens in human neurons link lysosomal failure to ferroptosis."
- **Per-gene fit:** Genome-wide CRISPRi/a survival hits in human iN.
- **Why:** Heavily cited Kampmann-lab paper. Companion to **#64
  Kampmann iNeuron RNA-seq** open ticket but is the genome-wide
  *screen*, not the per-gene KO RNAseq. Distinct dataset; probably
  wants its own ticket.

### 28. Tian 2019 — CRISPRi platform in iPSC neurons
- *Neuron* **104**, 239–255 (2019). PMID **31422865** /
  doi:10.1016/j.neuron.2019.07.014. ✓ corrected PMID. Title
  verified: "CRISPR Interference-Based Platform for Multimodal
  Genetic Screens in Human iPSC-Derived Neurons." (This is the
  CRISPRi platform paper, predecessor to Tian 2021.)
- **Per-gene fit:** Per-perturbation-target × per-gene-readout signed
  Z scores. Same schema as our existing perturb-seq datasets.

### 29. Dräger 2022 — CRISPRi/a in iPSC-derived microglia
- *Nat Neurosci* **25**, 1149–1162 (2022). PMID **35953545** ✓
  verified. Title: "A CRISPRi/a platform in human iPSC-derived
  microglia uncovers regulators of disease states." (Microglia, not
  iNeurons — corrected from earlier draft description.)
- **Per-gene fit:** Per-gene microglial-state-modifier hit tables.

### 30. Lalli 2020 — neural CRISPR screens of NDD genes
- *Genome Research* **30**, 1317–1331 (2020). PMID **32887689** /
  doi:10.1101/gr.262295.120. ✓ corrected PMID. Title verified:
  "High-throughput single-cell functional elucidation of
  neurodevelopmental disease-associated genes."
- **Per-gene fit:** Per-perturbed-gene × per-readout DEG matrices for
  ~30 NDD risk genes in human NPCs. Direct schema fit; tightly
  scoped to the SSPsyGene gene list.
- **Why:** One of the few studies specifically targeting the NDD
  gene list with functional perturbations in a human model.

### 31. Replogle 2022 — genome-wide Perturb-seq (K562)
- *Cell* **185**, 2559–2575 (2022). PMID **35688146** /
  doi:10.1016/j.cell.2022.05.013.
- **Per-gene fit:** Per-perturbed × per-readout DEG matrix at full
  genome scale.
- **Why:** Highest-cited Perturb-seq paper to date (1500+). Main
  caveat: K562 not neural — would be a "PPI / pathway" reference,
  not directly disease-relevant.
- **Caveats:** Off-tissue, so weight accordingly.

### 32. Joung 2023 — TF Atlas in hPSC
- *Cell* **186**, 209–229 (2023). PMID **36608654**.
- **Per-gene fit:** Per-TF-overexpression × per-readout differentiation
  outcome for ~1700 TFs. Several SSPsyGene TF genes are perturbed
  here.

---

## Tier 6 — Chromatin accessibility / regulatory genomics

### 33. Markenscoff-Papadimitriou 2020 — fetal cortex scATAC
- *Cell* **182**, 754–769 (2020). PMID **32610082** /
  doi:10.1016/j.cell.2020.06.002. ✓ corrected PMID. Title verified:
  "A Chromatin Accessibility Atlas of the Developing Human
  Telencephalon."
- **Per-gene fit:** Per-gene cell-type-specific accessibility +
  enhancer-gene linkage. Direct "is gene X regulated in cell type Y?".

### 34. Trevino 2021 — multiomic fetal cortex (scATAC + scRNA)
- *Cell* **184**, 5053–5069 (2021). PMID **34390642** /
  doi:10.1016/j.cell.2021.07.039.
- **Per-gene fit:** Per-gene developmental-trajectory + linked
  enhancer-peak scores.

### 35. Nott 2019 — cell-type-resolved myeloid epigenome
- *Science* **366**, 1134–1139 (2019). PMID **31727856**.
- **Per-gene fit:** Per-gene cell-type-specific (microglia / neuron /
  oligodendrocyte / astrocyte) epigenome features. Useful for
  microglia-disease links (SCZ C4, AD).

### 36. Gschwind 2023 — ENCODE rE2G enhancer-gene links **[DEFER — biorxiv-only]**
- bioRxiv 2023.11.09.563812 (posted 2023-11-13). PMID **38014075**
  is the *preprint* PubMed entry; no journal version yet (Engreitz
  Lab publications page still lists this as a bioRxiv preprint as
  of 2026-05-07). Project rule "skip biorxiv-only" (CLAUDE.md /
  memory) applies — defer until the Nature/Cell version posts.
- **Per-gene fit (when published):** Per-enhancer-gene-pair score
  across 352 cell types; >13M E-G interactions; per-gene aggregated
  enhancer-disease GWAS overlap. Direct fit for our **link table**
  schema once available.
- **Why:** Will be the canonical enhancer-gene resource for
  psychiatric GWAS variant interpretation when published. The 25.09
  Open Targets release already pulls from the preprint, indicating
  the field is treating it as authoritative even pre-publication.

---

## Tier 7 — Variant-level constraint resources

### 37. Karczewski 2020 — gnomAD constraint metrics (LOEUF, pLI)
- *Nature* **581**, 434–443 (2020). PMID **32461654** /
  doi:10.1038/s41586-020-2308-7.
- **Per-gene fit:** Per-gene LOEUF, pLI, mis_z, oe_lof, etc.
- **Why:** The *single* most-referenced per-gene constraint metric
  in psychiatric genetics. We currently have no constraint info on
  our per-gene cards — this is a glaring gap. Cited 6000+.
- **Caveats:** A v4 update (Chen S 2024 *Nature*, PMID **38057664**,
  "A genomic mutational constraint map using variation in 76,156
  human genomes" — corrected PMID) is out — likely better to use v4
  directly. Both are publicly redistributable.

### 38. Smith 2021 — UK Biobank brain imaging GWAS
- *Nat Neurosci* **24**, 737–745 (2021). PMID **33875891**.
- **Per-gene fit:** Per-gene MAGMA enrichment for ~3K brain imaging
  phenotypes.
- **Why:** Connects gene-level signal to brain-structural phenotypes
  — a different axis from the case-control GWAS papers above.
- **Caveats:** Heavy multi-phenotype data — would need UI thinking
  on how to surface "this gene is associated with N IDPs" without
  swamping the table.

---

## Tier 8 — iPSC disease models (per-gene KO transcriptomics)

These are similar in spirit to `polygenic-risk-20` and `xpo7-ipsc-neurons`
but for individual-gene KOs.

### 39. Schrode 2019 — SCZ polygenic risk in iPSC neurons
- *Nat Genet* **51**, 1475–1485 (2019). PMID **31548722** /
  doi:10.1038/s41588-019-0497-5. ✓ corrected PMID. Title verified:
  "Synergistic effects of common schizophrenia risk variants."

### 40. Stern 2018 — bipolar iPSC neuron sub-populations + lithium response
- *Mol Psychiatry* **23**, 1453–1465 (2018). PMID **28242870** /
  doi:10.1038/mp.2016.260. **Pass-2 correction:** "Linker 2020" was
  misremembered. The closest matching *Mol Psychiatry* paper on
  bipolar iPSC hippocampal-lineage neurons is Stern S et al. 2018,
  with a 2020 *Biol Psychiatry* follow-up (Stern S et al. 2020, PMID
  31732108) on dentate-gyrus / CA3 hyperexcitability that's a worthy
  alternate or complementary candidate.
- **Per-gene fit:** Per-gene DEG tables comparing iPSC-derived
  hippocampal-lineage neurons from BD-lithium-responders vs
  non-responders vs CTL. Per-gene log-fold-change + p-value; same
  shape as our existing iPSC-neuron datasets.
- **Why:** Bipolar iPSC functional model is a clean disease-axis
  comparator alongside the SCZ iPSC entries (Schrode 2019, #39) and
  ASD iPSC (Marchetto 2017, #41). Cited 700+.

### 41. Marchetto 2017 — ASD iPSC cortical neurons
- *Mol Psychiatry* **22**, 820–835 (2017). PMID **27378147** ✓
  verified. Title: "Altered proliferation and networks in neural
  cells derived from idiopathic autism."

These three are clear "per-gene DEG tables of disease-vs-control iPSC
neuron differentiations" papers — the same shape as several of our
existing datasets.

---

## Tier 9 — Protein-protein interaction maps for ASD/SCZ genes

PPI is currently absent from our site (#5 was deferred biorxiv-only).
Open published candidates:

### 42. Pintacuda 2023 — autism-gene PPI in iPSC neurons
- *Cell Genomics* **3**, 100250 (2023). PMID **36950384** /
  doi:10.1016/j.xgen.2023.100250. ✓ corrected PMID. Title verified:
  "Protein interaction studies in human induced neurons indicate
  convergent biology underlying autism spectrum disorder."
- **Per-gene fit:** Per-bait × per-prey edge table for ASD-gene
  baits in iN. Direct fit for our **link table** schema.
- **Why:** Pintacuda is also a Wamsley/Gordon collaborator (her name
  appears in `hsc-asd-organoid-m5`'s author list) — likely
  consortium-friendly to ingest. A companion preview is **Bicks 2023**
  *Cell Genom* (PMID **36950377**, "Neuronal protein interaction
  networks in autism spectrum disorder") — Lucy Bicks is also on the
  Wamsley team.
- **Caveats:** Smaller scope than what #5 (Obernier 2024 atlas) would
  give us, but it's *published*, which #5 is not.

### 43. ~~Sanders 2018 — ASD constraint~~ **DROPPED**
- Pass-2 outcome: no first-author Sanders 2018 ASD per-gene paper
  matches the drafted description; this entry was a recall conflation
  with Sanders 2015 *Neuron* (PMID 26402605, already in Tier 10) or
  with the TADA-A non-coding extension. Slot retired; numbering kept
  for traceability. No replacement candidate — Tier 11 (#44+) below
  picks up the slack with newer entries.

---

## Tier 10 — Honourable mentions / older-but-seminal

Pre-2017 papers I'd still pick up if a wrangler is looking for a
half-day project:

- **Sanders 2015** *Neuron* (PMID **26402605**) — TADA combined
  exome ASD; the methodology Satterstrom 2020 builds on. The 65-gene
  list still gets cited.
- **Iossifov 2014** *Nature* (PMID **25363768**) — SSC ASD de novo
  variants. Still the canonical SSC reference per-gene table.
- ~~**Marshall 2017 ASD CNVs**~~ **DROPPED** — no such paper
  exists. PMID 28263302 is **Yuen 2017** *Nat Neurosci* ("Whole
  genome sequencing resource identifies 18 new candidate genes for
  autism spectrum disorder") — different paper, different scope, but
  *also* a valid candidate; flagging it here under its correct
  citation. Marshall CR 2017 *Nat Genet* (PMID 27869829) is the
  *schizophrenia* CNV paper, not ASD.
- **Yuen 2017** *Nat Neurosci* (PMID **28263302**) — WGS of ~5K MSSNG
  ASD families; per-gene candidate-gene table. Replaces the dropped
  Marshall entry.
- **De Rubeis 2014** *Nature* (PMID **25363760**) — TADA on ASC
  exome. Companion to Iossifov 2014 in the same issue.
- **Coe 2014** *Nat Genet* — DD CNVs.

---

## Tier 11 — Added in pass 2 (2026-05-07)

These entries fall into two groups: cross-check additions surfaced as
side-effects of the pass-1 PMID corrections, and new high-impact
2022–2025 candidates the original recall draft missed. All
peer-reviewed (the "skip biorxiv-only" rule still applies).

### Cross-check additions from pass 1

#### 44. Amiri 2018 — PsychENCODE organoid transcriptome/epigenome
- *Science* **362**, eaat6720 (2018). PMID **30545853** /
  doi:10.1126/science.aat6720. Title: "Transcriptome and epigenome
  landscape of human cortical development modeled in organoids."
- **Per-gene fit:** Per-gene developmental-trajectory expression in
  hPSC-derived cortical organoids, paired with CTL fetal cortex from
  Li 2018; companion paper to Wang 2018 (#22) and Li 2018 (#23) in
  the same PsychENCODE 1.0 issue.
- **Why:** Surfaced during pass-1 verification of #23 (drafted PMID
  was actually Amiri's). Worth its own entry — the only PsychENCODE
  1.0 paper with primary organoid data, useful as the validation
  reference for downstream organoid datasets
  (`brain_organoid_atlas`, Wamsley, Bhaduri).

#### 45. Finucane 2018 — LDSC-SEG per-tissue heritability
- *Nat Genet* **50**, 621–629 (2018). PMID **29632380** /
  doi:10.1038/s41588-018-0081-4. Title: "Heritability enrichment of
  specifically expressed genes identifies disease-relevant tissues
  and cell types."
- **Per-gene fit:** Per-tissue / per-cell-type LD-score-regression
  heritability enrichment across 53 GTEx tissues + 152 cell types.
  Per-gene "specifically expressed gene" (SEG) sets are also
  released and are the primary input for downstream LDSC-SEG runs.
- **Why:** Surfaced during pass-1 verification of #19 Skene
  (drafted PMID was actually Finucane's). The LDSC-SEG framework
  is heavily cited (1500+) and complementary to Skene 2018 EWCE
  (#19) and Bryois 2020 (#20) — most cell-type-GWAS papers run
  both methods; we should ingest both reference resources.

#### 46. Yao 2021 — mouse primary motor cortex multi-omic atlas
- *Nature* **598**, 103–110 (2021). PMID **34616066** /
  doi:10.1038/s41586-021-03500-8. Title: "A transcriptomic and
  epigenomic cell atlas of the mouse primary motor cortex."
- **Per-gene fit:** Per-cell-type marker tables (transcriptomic +
  epigenomic) at deeper resolution than the cross-species capstone
  Yao 2021 *Nature* (PMID 34616075, #17 above) since it focuses on
  mouse only.
- **Why:** Surfaced as a companion to #17 BICCN 2021. Mouse-only
  deeper analysis; pairs naturally with mouse-cohort datasets
  already in our DB (`mouse-cortex-perturb-4tf`, `mouse-perturb-4tf`).

#### 47. Li YE 2023 — comparative atlas of single-cell chromatin accessibility
- *Science* **382**, eadf7044 (2023). PMID **37824643** /
  doi:10.1126/science.adf7044. Title: "A comparative atlas of
  single-cell chromatin accessibility in the human brain."
- **Per-gene fit:** Per-cell-type accessibility + linked-gene
  predictions across adult human brain; companion to Siletti 2023
  (#18) and Velmeshev 2023 (#12) in the same Science issue.
- **Why:** Allen / Ren-lab; covers chromatin where Siletti covers
  transcription. Pairs naturally with Markenscoff-Papadimitriou
  2020 (#33) and Trevino 2021 (#34) for fetal-vs-adult chromatin
  accessibility coverage.

#### 48. Bicks 2023 — autism-gene PPI in iPSC neurons (companion preview)
- *Cell Genom* **3**, 100279 (2023). PMID **36950377** /
  doi:10.1016/j.xgen.2023.100279. Title: "Neuronal protein
  interaction networks in autism spectrum disorder."
- **Per-gene fit:** Companion preview / commentary alongside
  Pintacuda 2023 (#42); not a primary data paper. Likely **skip
  ingestion** but flag — Lucy Bicks is on the Wamsley team
  (#55), so the perspective informs how the wrangler team frames
  the Pintacuda PPI dataset.

#### 49. Bae 2022 — somatic mutations in 131 human brains
- *Science* **377**, 511–517 (2022). PMID **35901164** /
  doi:10.1126/science.abm6222. Title: "Analysis of somatic
  mutations in 131 human brains reveals aging-associated
  hypermutability."
- **Per-gene fit:** Per-gene somatic mutation burden across 131
  brains (CTL + ageing + neuropsychiatric); per-gene
  hypermutability scores. Direct fit for "is this gene
  somatically unstable in adult brain?" queries.
- **Why:** Brain Somatic Mosaicism Network (BSMN) flagship paper.
  Somatic-mosaicism is currently absent from the site and is a
  recognized SSPsyGene-adjacent topic.

#### 50. Garrison 2023 — BSMN data resource
- *Sci Data* **10**, 813 (2023). PMID **37985666** /
  doi:10.1038/s41597-023-02645-7. Title: "Genomic data resources
  of the Brain Somatic Mosaicism Network for neuropsychiatric
  diseases."
- **Per-gene fit:** Resource paper describing the BSMN data
  deposits; not a primary per-gene table but the gateway to
  downstream BSMN per-gene analyses (Bae 2022 above included).
  Likely **link as a `reference` rather than a primary dataset**.
- **Why:** If Bae 2022 lands, this is the metadata anchor. Not a
  standalone dataset candidate.

### Newly surfaced 2022–2025 candidates (pass 2 web search)

#### 51. Zhou 2022 — moderate-risk ASD genes (42K cases)
- *Nat Genet* **54**, 1305–1319 (2022). PMID **35982159** /
  doi:10.1038/s41588-022-01148-2. Title: "Integrating de novo and
  inherited variants in 42,607 autism cases identifies mutations
  in new moderate-risk genes."
- **Per-gene fit:** TADA-style per-gene exome-wide significance
  (60 genes at P<2.5×10⁻⁶, 5 new: NAV3, ITSN1, MARK2, SCAF1,
  HNRNPUL2). Direct schema fit alongside Satterstrom 2020 (#1)
  and Fu 2022 (#2).
- **Why:** Largest combined de novo + inherited ASD gene
  discovery to date; complements (does not replace) the de-novo-
  focused Satterstrom 2020. The "moderate-risk" tier of NAV3 /
  ITSN1 / SCAF1 / HNRNPUL2 is novel signal not in Satterstrom or
  Fu and is being heavily cited going forward.

#### 52. Wright 2023 — DDD genomic diagnosis (~13K probands)
- *N Engl J Med* **388**, 1559–1571 (2023). PMID **37043637** /
  doi:10.1056/NEJMoa2209046. Title: "Genomic Diagnosis of Rare
  Pediatric Disease in the United Kingdom and Ireland."
- **Per-gene fit:** Updates Kaplanis 2020 (#10) with additional
  trios + reanalysis; 60 new DD genes called. Per-gene diagnostic
  yield + de novo burden per gene.
- **Why:** Successor to Kaplanis 2020 in the DDD series. If
  Kaplanis is too old to bother with, Wright 2023 is the entry to
  pick instead.

#### 53. O'Connell 2025 — PGC bipolar update (~158K cases)
- *Nature* **639**, 968–975 (2025). PMID **39843750** /
  doi:10.1038/s41586-024-08468-9. Title: "Genomics yields
  biological and phenotypic insights into bipolar disorder."
- **Per-gene fit:** 298 GWS loci → 36 mapped genes; per-gene
  MAGMA / fine-mapping / cell-type-enrichment tables. Direct
  successor to Mullins 2021 (#5).
- **Why:** Largest BD GWAS to date (≥4× Mullins 2021). When
  ingesting BD coverage, prefer this over Mullins; bundle them
  the way #56 bundles Gandal 2018 + 2022 if both are wanted.

#### 54. Strom 2025 — OCD GWAS (53K cases)
- *Nat Genet* **57**, 1389–1401 (2025). PMID **40360802** /
  doi:10.1038/s41588-025-02189-z. Title: "Genome-wide analyses
  identify 30 loci associated with obsessive-compulsive disorder."
- **Per-gene fit:** 30 GWS loci → 249 candidate effector genes
  (25 high-confidence: WDR6, DALRD3, CTNND1 + MHC genes). Per-gene
  MAGMA / fine-mapping. Cell-type enrichment for excitatory /
  D1 / D2 medium-spiny neurons.
- **Why:** First well-powered OCD GWAS; OCD is a fourth currently-
  absent disease axis (BD, ADHD, MDD, OCD). Pairs with Cross-
  Disorder PGC 2019 (#8) for cross-disorder framing.
- **Caveats:** OCD is part of the broader anxiety / compulsive
  spectrum that's relatively under-represented in the SSPsyGene
  250 — relevance to that gene list is weaker than ASD/SCZ.

#### 55. Wen 2024 — PsychENCODE 2 cross-ancestry developmental brain atlas
- *Science* **384**, eadh0829 (2024). PMID **38781368** /
  doi:10.1126/science.adh0829. Title: "Cross-ancestry atlas of
  gene, isoform, and splicing regulation in the developing human
  brain."
- **Per-gene fit:** Per-gene / per-isoform / per-splice-event
  expression QTLs across the developing brain in EUR + AFR
  ancestry. Companion to Emani 2024 (already loaded as
  `psychscreen`) but covers *developmental* rather than adult
  brain.
- **Why:** Fills the developmental-brain gap that `psychscreen`
  (adult) leaves open. Pairs naturally with Werling 2020 (#24)
  and Li 2018 (#23).
- **Caveats:** Heavy overlap with `psychscreen` schema — should be
  loaded as a sibling dataset, not a replacement.

#### 56. Deng 2024 — PsychENCODE 2 regulatory elements in developing cortex
- *Science* **384**, eadh0559 (2024). PMID **38781390** /
  doi:10.1126/science.adh0559. Title: "Massively parallel
  characterization of regulatory elements in the developing human
  cortex."
- **Per-gene fit:** Per-element MPRA activity scores + per-gene
  linked-element aggregations. Pairs with Markenscoff-Papadimitriou
  2020 (#33) and Trevino 2021 (#34).
- **Why:** The MPRA companion to the developmental-cortex atlas
  series. If we ingest #33 / #34, this is the validation layer.

#### 57. Bryois 2022 — eight-cell-type brain cis-eQTLs **(also worth filing)**
- *Nat Neurosci* **25**, 1104–1112 (2022). PMID **35915177** /
  doi:10.1038/s41593-022-01128-z. Title: "Cell-type-specific
  cis-eQTLs in eight human brain cell types identify novel risk
  genes for psychiatric and neurological disorders."
- **Per-gene fit:** Per-gene cis-eQTL summary stats in 8 brain
  cell types (ExN, InN, AST, MGL, OLI, OPC, END, PER); GWAS
  colocalization tables for ASD, SCZ, BIP, MDD, AD, PD.
- **Why:** Cleaner "Bryois cell-type" reference than the
  single-cell PsychENCODE2 papers — fewer donors but more direct
  cell-type-resolved per-gene effect sizes. Surfaced during
  pass-2 verification of the misremembered "Bryois 2024 PWAS"
  (#21 above).

---

## Out-of-scope but worth flagging to PIs

Things I'd *not* recommend ingesting but that come up often enough
that the team should know they exist:

- **Allen Brain Cell Atlas / Yao 2023 mouse brain** — gigantic, but
  we already have Polioudakis-style human cell types covered. Mouse
  atlas is better consumed via `cellxgene` or the Allen portal.
- **Per-disorder PRS papers** — usually no per-gene readout; PRS is
  a polygenic *score*, not a per-gene quantity. Skip unless the paper
  also publishes per-gene LDSC / MAGMA.
- **GTEx** — already embedded in PsychENCODE / TWAS papers; standalone
  ingestion is more work than it's worth.
- **ENCODE candidate cis-regulatory elements (cCREs)** — not per-gene
  natively; would need an enhancer-to-gene aggregation (Gschwind 2024
  rE2G handles that; ingest the rE2G output if anything).

---

## Suggested triage for next ticket round

Highest expected value (well-published, clean per-gene supps, clear
gap):

1. **Satterstrom 2020 + Fu 2022 ASD gene tables** (Tier 1) — pair
   them; together they replace SFARI 2010 as the primary ASD gene
   ranking on the site.
2. **Singh 2022 SCHEMA + Trubetskoy 2022 PGC SCZ3** (Tier 1) — pair
   them; gives full common+rare SCZ coverage. Direct comparator to
   the ASD pair.
3. **Karczewski 2020 / Chen 2024 gnomAD constraint** (Tier 7) — high
   utility per unit work; would surface LOEUF/pLI on every gene card.
4. **Velmeshev 2019 ASD cortex scRNA** (Tier 2) — comparator for
   the already-loaded Wamsley 2024 (#55), and the DEG list is open
   in Suppl while Wamsley's is gated.
5. **Cross-Disorder PGC 2019** (Tier 1) + **Bryois 2020 cross-disorder
   cell types** (Tier 3) — pair them; activates the cross-disorder
   framing across the whole site at once.
6. **Pintacuda 2023 ASD-gene PPI** (Tier 9) — first published
   PPI dataset, replaces the deferred #5.
7. **Mullins 2021 bipolar + Demontis 2023 ADHD + Als 2023 depression**
   (Tier 1) — fills the three currently-absent disease axes.

Lower expected value but worth filing tickets so the wrangler team
can pick them up opportunistically:

- Wang 2018 / Li 2018 PsychENCODE bulk (Tier 4).
- Tian 2021 CRISPRi iN + Lalli 2020 ASD-gene CRISPR (Tier 5).
- Markenscoff-Papadimitriou 2020 / Trevino 2021 / Nott 2019 (Tier 6).
- Polioudakis 2019 / Bhaduri 2020 / Kanton 2019 / Velmeshev 2023
  (Tier 2 — partial overlap with `brain_organoid_atlas` /
  `wamsley-postmortem-asd`; check before ingesting).

Per the "skip biorxiv-only" rule already in `CLAUDE.md` / memory:
*every* candidate above has a peer-reviewed home; no biorxiv-only
papers in this list.

## Verification log — pass 2 (2026-05-07)

Pass 2 ran with WebSearch / WebFetch restored. NCBI eutils
(`esummary.fcgi`) and targeted Google searches were used to resolve
the five `[VERIFY]` items, fold in seven cross-check additions, and
surface eight 2022–2025 candidates that hadn't been on the original
recall list.

Before opening any ticket, the standard duplicate check still
applies:

```bash
gh issue list --repo sspsygene-dracc/psypheno --state all \
    --search "<first-author> <year>" --limit 5
```

### `[VERIFY]` items resolved

| # | Original draft | Pass-2 resolution |
|---|----------------|-------------------|
| 21 | "Bryois 2024 PWAS" *Nat Neurosci* | **Replaced** with Luo J et al. 2024 *Mol Psychiatry* (PMID 38724566) — brain proteome QTLs + MR against psychiatric GWAS. No first-author Bryois 2024 paper exists; Bryois is a co-author here. **Bryois 2022** *Nat Neurosci* eight-cell-type cis-eQTL (PMID 35915177) was added as #57 — that's likely what the drafter actually had in mind. |
| 26 | "Jaffe 2020 DLPFC SCZ" | **Replaced** with Jaffe AE et al. 2018 *Nat Neurosci* (PMID 30050107). The 2020 framing was wrong; the BrainSeq Phase 1 DLPFC SCZ paper is from 2018. |
| 36 | "Gschwind 2024 rE2G" *Nature* | **Marked DEFER** (was bioRxiv-only as of 2026-05-07). PMID 38014075 indexes the bioRxiv preprint; the Engreitz Lab publications page still lists this as a preprint. Project rule "skip biorxiv-only" applies — revisit when the journal version posts. |
| 40 | "Linker 2020 bipolar iPSC" *Mol Psychiatry* | **Replaced** with Stern S et al. 2018 *Mol Psychiatry* (PMID 28242870) — bipolar iPSC neuron sub-populations / lithium response. The "Linker 2020" name was misremembered; closest companion is Stern 2020 *Biol Psychiatry* (PMID 31732108) on dentate-gyrus hyperexcitability. |
| 43 | "Sanders 2018 ASD constraint" | **Dropped.** No matching Sanders 2018 paper; recall conflation with Sanders 2015 *Neuron* (already in Tier 10). Slot retired with a tombstone for traceability. |

### Cross-check additions folded in (Tier 11, #44–#50)

All seven candidates pass-1 flagged were verified by `esummary` and
added with full citations + per-gene fit + why:

- **#44 Amiri 2018** *Science* (PMID 30545853) — PsychENCODE 1.0 organoid transcriptome / epigenome companion.
- **#45 Finucane 2018** *Nat Genet* (PMID 29632380) — LDSC-SEG; per-tissue/cell-type heritability enrichment.
- **#46 Yao Z 2021** *Nature* (PMID 34616066) — mouse motor cortex multi-omic atlas (companion to BICCN 2021 #17).
- **#47 Li YE 2023** *Science* (PMID 37824643) — comparative single-cell chromatin accessibility atlas, adult human brain.
- **#48 Bicks 2023** *Cell Genom* (PMID 36950377) — companion preview to Pintacuda 2023; flagged but probably **skip ingestion**.
- **#49 Bae 2022** *Science* (PMID 35901164) — somatic mutations in 131 human brains; BSMN flagship.
- **#50 Garrison 2023** *Sci Data* (PMID 37985666) — BSMN data-resource metadata paper; tag as `reference`, not a primary dataset.

### New pass-2 candidates (Tier 11, #51–#57)

Found via fresh WebSearch in scope (Cell / Nature / Science /
Nat Genet / Nat Neurosci, per-gene readouts, neuropsych / NDD,
peer-reviewed):

- **#51 Zhou 2022** *Nat Genet* (PMID 35982159) — moderate-risk ASD genes from 42K cases; sibling to Satterstrom 2020 / Fu 2022.
- **#52 Wright 2023** *NEJM* (PMID 37043637) — DDD genomic-diagnosis update; successor to Kaplanis 2020 (#10).
- **#53 O'Connell 2025** *Nature* (PMID 39843750) — PGC bipolar update at ~158K cases; successor to Mullins 2021 (#5).
- **#54 Strom 2025** *Nat Genet* (PMID 40360802) — first well-powered OCD GWAS (30 loci, 53K cases). Adds OCD as a fourth disease axis.
- **#55 Wen 2024** *Science* (PMID 38781368) — PsychENCODE 2 cross-ancestry developmental brain atlas. Sibling to the already-loaded `psychscreen` (Emani 2024 PMID 38781369), but covers developmental rather than adult brain.
- **#56 Deng 2024** *Science* (PMID 38781390) — PsychENCODE 2 MPRA characterization of regulatory elements in developing cortex.
- **#57 Bryois 2022** *Nat Neurosci* (PMID 35915177) — eight-brain-cell-type cis-eQTLs; the paper most likely confused with the misremembered "Bryois 2024 PWAS" of #21.

### Other candidates considered and skipped

- **Zheng X et al. 2024** *Cell* (PMID 38772369) — in-vivo Perturb-seq cortical development. Already in flight as ticket [#52](https://github.com/sspsygene-dracc/psypheno/issues/52) (Zheng / Jin 2026).
- **Replogle 2024 / Multiome Perturb-seq** — Replogle followups on Perturb-seq methodology; published in *Cell Systems*, not in scope (methodology, not a per-gene readout).
- **Kampmann lab "Massively parallel CRISPR-based Screening Platform for Modifiers of Neuronal Activity"** (2024) — still bioRxiv-only as of 2026-05-07; defer.
- **SingleBrain 2025 sn-eQTL meta-analysis** — still medRxiv-only as of 2026-05-07; defer.
- **Benjamin 2022** *Nat Neurosci* (PMID 36319771) — caudate-nucleus SCZ DEGs (LIBD lab). Mentioned inline under #26 but not promoted to its own slot; worth filing if striatal coverage becomes a priority.

### Tier 1 supplementary-table confirmation

Per-gene supp tables for the Tier 1 high-priority candidates were
confirmed via NCBI/PMC during pass 1 (supp table numbers cited
inline in each entry). Pass 2 did **not** re-open every PMC
full-text — the Tier 1 supp-number annotations are pass-1 work.
The newer pass-2 candidates (#51–#57) cite per-gene table location
in their own entries; verify before filing each ticket.

### Items not (yet) re-checked in pass 2

- The Tier 1 PMC full-texts for Howard 2019 / Als 2023 / Cross-Disorder PGC 2019 — pass 1 noted "Suppl tables exist" without pinning a number. Worth a 5-min scan before filing those tickets, but not a blocker for triage.
- Demontis 2023 vs. Demontis 2019 (PMID 30478444) — pass 1 noted Demontis 2023 supersedes; not separately re-checked in pass 2.
