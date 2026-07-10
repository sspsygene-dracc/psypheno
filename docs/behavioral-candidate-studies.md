# Candidate BEHAVIORAL studies for psypheno ingestion

A follow-up to [`candidate-studies.md`](candidate-studies.md), which was geared
toward high-throughput molecular data (RNA-seq, scRNA-seq, CRISPR screens,
GWAS/exome per-gene tables). This memo deliberately **de-emphasizes omics** and
surfaces **behavioral** readouts — mouse phenotyping batteries, ultrasonic
vocalization, machine-vision behavior, home-cage monitoring, and human
behavioral instruments — in neurodevelopmental / autism / neuropsychiatric
contexts.

**Crucial filter:** only datasets where machine-readable per-gene /
per-strain / per-genotype behavioral data is genuinely **downloadable**
(supplementary tables, public repository deposits, or database bulk exports).
Studies that publish behavioral results only as figures are flagged but ranked
below. Candidates are ordered by (1) data actually downloadable + machine-
readable, (2) per-gene / per-strain mappability, (3) neurodev/autism relevance.

Provenance: reconstructed from a deep-research literature sweep (20 fetched
primary sources, adversarially verified claims). Every "downloadable"
assertion below traces to a verified source; per-paper caveats note where
downloadability is *unconfirmed* and needs a supplement check before ingestion.

---

## Headline findings

- The strongest behavioral fits are **database resources**, not one-off papers
  — because they publish machine-readable per-gene/per-strain tables, whereas
  most behavioral papers ship figures only.
- The two labs called out for investigation split cleanly:
  - **Vivek Kumar (JAX) — strong yield.** Three deposited machine-vision
    behavioral-genetics datasets, several including ASD/NDD mutant lines and
    QTL→gene mapping, all downloadable (Mouse Phenome Database, Zenodo, Harvard
    Dataverse).
  - **Joseph Dougherty (WashU) — little currently ingestible.** No recent
    publication with a cleanly downloadable per-gene behavioral table was found;
    the nearest handle is ultrasonic-vocalization methods work. Revisit later.

---

## Tier B1 — Database resources with downloadable per-gene / per-strain behavioral data

The highest-value targets: consortium/curated databases that expose behavioral
readouts already keyed to genes or strains, in bulk machine-readable form.

### B1. IMPC — International Mouse Phenotyping Consortium *(single best fit)*
- Groza et al. 2023, *Nucleic Acids Research* **51**, D1038. PMID 36305833 /
  doi:10.1093/nar/gkac972. Portal architecture: Koscielny et al. 2014,
  *NAR* **42**, D802 (PMID 24194600).
- **Behavioral phenotypes:** standardized behavioral/neurological pipeline —
  open field (anxiety / exploration / activity), acoustic startle & PPI, grip
  strength (neuromuscular), SHIRPA.
- **Model:** mouse single-gene knockouts. **Data Release 24 (Mar 2026):
  9,605 knockout genes, 10,341 phenotyped lines, 138M+ data points, 111,664
  statistically significant per-gene phenotype calls.** Behavioral is among the
  leading phenotype categories examined.
- **Downloadable:** yes — REST/Solr **API**, bulk **FTP** dumps (parquet/CSV)
  captured per data release, and a **batch-query** tool at mousephenotype.org.
  Data is consortium-generated (not literature-aggregated) and **already
  gene-mapped with statistical calls** — the cleanest per-gene behavioral source
  available.
- **Why:** every readout is per-gene keyed with a stat call; huge ASD/NDD gene
  overlap (most ASD genes have KO lines). Mouse.

### B2. AutDB / SFARI Gene Animal Model module — Das et al. 2019
- *Molecular Autism* **10**, 11 (2019). doi:10.1186/s13229-019-0263-7 /
  PMC6417187.
- **Behavioral phenotypes:** curated phenoterm/phenovalue annotations
  (Increased / Decreased / Abnormal / No Change) across **450+ experimental
  paradigms** — core ASD domains (social interaction, ultrasonic vocalization,
  repetitive behavior) plus anxiety, seizures, motor, learning/memory. Top
  annotated measures: general locomotor activity, anxiety, social interaction.
- **Model:** rodent ASD models — **258 ASD-linked genes, 6 CNV regions, 72
  environmental inducers, 9 inbred strains, curated from 787 publications**
  (compared with ~60 ASD genes in MGI as of Aug 2018). The Shank3 case study
  alone annotates 27 loss-of-function models separately (15 KO + 10 KI mouse,
  2 KO rat), showing construct/strain-level resolution.
- **Downloadable:** yes — **supplementary tables S1–S9 (.xlsx / .docx)** with
  construct and phenotype data; the full dataset lives in AutDB
  (autism.mindspec.org/autdb, mirrored at gene.sfari.org/autdb). This is a
  genuine per-gene behavioral **annotation** database — direct fit for our
  per-gene schema.
- **Caveat:** the SFARI Gene animal-models *landing-page* CSV export
  (`download-csv.php?api-endpoint=animal-genes`, ~269 models) contains **only
  summary fields** (model counts, synteny status, human gene scores,
  syndromic/rescue class) — **not** the detailed behavioral readouts. Those live
  in the Das et al. S1–S9 supplement and on individual gene pages. Ingest from
  the supplement / AutDB, not the landing CSV.

### B3. Mouse Phenome Database (MPD)
- Bogue et al. 2020, *NAR* **48**, D716. PMID 31696236. phenome.jax.org (JAX).
- **Behavioral phenotypes:** curated strain-survey behavior — open-field
  thigmotaxis / anxiety, activity, sociability, behavioral despair, grooming.
  "Behavior tests" is a first-class browsable category.
- **Model:** 2,000+ mouse strains/populations (inbred, Collaborative Cross,
  Diversity Outbred, transgenic). Per-**strain** (maps to genetic background),
  not per-gene-KO.
- **Downloadable:** yes — bulk **CSV / CSV.GZ** at phenome.jax.org/downloads
  (`strainmeans.csv.gz` = strain averages + stats; `animaldatapoints.csv.gz` =
  one row per animal; `measurements.csv`, `straininfo.csv` for metadata) plus a
  JSON/CSV **API**. Canonical deposit target for JAX behavioral surveys —
  **hosts the Kumar lab datasets below (projects Kumar3, Kumar4).** Mouse.

### B4. MGI Mammalian Phenotype Ontology gene→phenotype reports
- Mouse Genome Informatics, informatics.jax.org. Ongoing resource (no single
  paper).
- **Behavioral phenotypes:** Mammalian Phenotype (MP) ontology categorical
  annotations under the "abnormal behavior" / "nervous system phenotype"
  branches.
- **Model:** mouse genes/alleles. **The most directly per-gene-mappable**
  resource in this list.
- **Downloadable:** yes — flat **TSV** report files (`MGI_GenePheno.rpt`,
  `MGI_PhenoGenoMP.rpt`) linking genes/alleles → MP behavioral terms; also
  MouseMine programmatic access. Categorical (annotation), **not** quantitative
  readouts — weigh accordingly. Mouse.

---

## Tier B2 — Vivek Kumar lab: machine-vision behavioral genetics

Per-**strain**, machine-readable, and several include ASD/NDD mutant lines with
QTL→gene mapping. This is the Kumar deliverable. Central download hub:
**kumarlab.org/resources**.

### B5. Geuther et al. 2021 — automated grooming (repetitive behavior)
- *eLife* **10**, e63207 (2021). doi:10.7554/eLife.63207.
- **Behavioral:** neural-network-scored grooming quantity + patterning, plus
  open-field anxiety/activity. Grooming is an ASD-relevant repetitive behavior.
- **Model / scale:** 2,457 mice across 62 strains (43 classical laboratory,
  8 wild-derived, 11 F1 hybrid). GWAS → **130 QTL** mapping to neurodev genes
  including **Sox5, FoxP1, Ctnnb1, Grin2b**.
- **Downloadable:** behavioral data in **MPD project Kumar3**
  (phenome.jax.org/projects/Kumar3); **Supplementary file 2** = pathway / gene
  table; Zenodo 10.5281/zenodo.4646088; code/models on GitHub (KumarLabJax).
  Mouse — per-strain, plus per-QTL-gene associations.

### B6. Sheppard et al. 2022 — stride-level gait *(best single-paper fit)*
- *Cell Reports* **38**, 110231 (2022). doi:10.1016/j.celrep.2021.110231 /
  PMID 35021077.
- **Behavioral:** 14 stride-level gait + open-field posture metrics (stride
  speed / length, step length / width, limb duty factor, temporal symmetry,
  lateral displacement, angular velocity) via deep-learning pose estimation
  (12 keypoints per frame).
- **Model / scale:** 62 strains, 1,898 animals — **plus explicit ASD/NDD mutant
  models: Mecp2 (Rett), Fmr1, Shank3, Cntnap2, Del4Aam (ASD)** alongside
  SOD1-G93A (ALS) and Ts65Dn (Down). Directly per-gene mappable for the mutant
  lines.
- **Downloadable:** **MPD project Kumar4**; training/validation data + network
  weights on Zenodo 10.5281/zenodo.5708437; code on GitHub (KumarLabJax:
  deep-hrnet-mouse, gaitanalysis). Mouse.

### B7. JABS — JAX Animal Behavior System (Kumar lab)
- *eLife* **14**, e107259 (2025) — peer-reviewed successor to the 2022 bioRxiv
  preprint.
- **Behavioral:** grooming, posture, gait, left/right turning, rearing
  (supported/unsupported), scratching, escape attempts, plus higher-order
  constructs (biological age, pain, seizure intensity). Heritability, genetic
  correlations, and GWAS across ~168 genetically diverse strains.
- **Downloadable:** curated datasets **JABS600 (598 videos, 60 strains),
  JABS1200 (1,139 videos, 60 strains), JABS-BxD (1,083 videos, 108 BxD
  strains)** on Harvard Dataverse (doi:10.7910/DVN/SAPNJG,
  doi:10.7910/DVN/RQYI04) — video recordings + keypoint files. Full software /
  hardware stack open-source on GitHub (KumarLabJax/JABS-data-pipeline,
  mouse-tracking-runtime). Mouse.
- **Caveat:** deposits are video + keypoint, not a tidy per-gene summary CSV;
  per-gene mapping is via the strain-level GWAS, not a KO panel. More work to
  reduce to an ingestible table than B5/B6.

---

## Tier B3 — Ultrasonic vocalization (per-gene autism models, downloadability weak)

The right modality for the Dougherty vocalization axis, but **none currently
ships a confirmed machine-readable per-gene USV table.** Treat as watch-items
pending a supplement/deposit check, not ingest-ready.

- **Crmp4 / Dpysl3 KO USV** — PMC9139187. Isolation-induced calls classified
  into 10 call types with per-genotype × per-sex counts; highly per-gene
  mappable. **Readouts in figures/in-paper tables only; no confirmed
  supplementary spreadsheet or deposit.** Mouse.
- **NS-Pten (neuron-subset Pten) KO USV** — PMC5698873. PTEN is an ASD gene;
  per-genotype call counts, duration, peak amplitude at PND8/PND11. Strong
  relevance. **In-paper only; verify for a supplement before ingestion.** Mouse.
- **G-Node USV deposit** — doi:10.12751/g-node.w7lzc3 (Han/Jung/Choi 2025). A
  real open deposit of isolation-induced pup USVs, **but wild-type C57BL/6 only
  (no genotype dimension)** and shipped as a single ~14 GiB ZIP of raw
  250–300 kHz audio — no per-gene summary table. Not per-gene-ingestible.
- **VocalMat** — Fonseca et al. 2021, *eLife* **10**, e59161.
  doi:10.7554/eLife.59161. A MATLAB computer-vision tool that classifies USVs
  into 11 types; OSF deposit (osf.io/bk2uj) holds 12,954 labeled **training
  images**, not per-gene tables. Method/tool, not a gene-mapped dataset — useful
  as the analysis layer for a future USV dataset.
- **Dougherty-adjacent USV methods** — mountable miniature microphones for
  per-animal USV assignment (*Cell Reports Methods* 2025). A method paper;
  no ingestible per-gene table.

---

## Tier B4 — Human behavioral phenotypes (deeply phenotyped but access-gated)

- **Simons Simplex Collection (SSC) + SPARK, via SFARI Base** — deep human
  phenotyping (SCQ-Lifetime, Repetitive Behavior Scale-Revised, CBCL 6-18,
  ADOS/ADI-R, IQ). Per-individual, per-gene-condition. **Gated behind a SFARI
  Base data-use agreement, not an open journal supplement** — human, per-gene
  mappable, but not openly ingestible.
- **Litman et al. 2025** — PMC12283356, "Decomposition of phenotypic
  heterogeneity in autism." SPARK (n=5,392) + SSC (n=861) across 239 behavioral
  features in 7 categories (limited social communication, restricted/repetitive
  behavior, attention deficit, disruptive behavior, anxiety/mood, developmental
  delay, self-injury). Raw phenotype data gated; **Supplementary Data 1 CSV
  (421 KB) is ASD-relevant gene *sets*** (a gene-level artifact, not per-gene
  behavioral readouts). Code: github.com/FunctionLab/asd-pheno-classes; Zenodo
  10.5281/zenodo.15324658. Human.

---

## Not ingestible (reviews / methods / protocols — provenance value only)

- **Kazdoba, Leach & Crawley 2016** — *behavioral phenotypes of genetic mouse
  models of autism* review (PMID 26403076). Defines the phenotype vocabulary
  (social, USV, repetitive grooming, anxiety, hyperactivity, cognitive
  flexibility, sensory reactivity) across 100+ single-gene models, but is a
  narrative review with no downloadable per-genotype file.
- **Moy et al. 2007** — 10-inbred-strain autism-relevant behavioral survey
  (identified BTBR as the low-sociability model). Pre-2017, but the underlying
  data is live and downloadable **in MPD** — reach it via B3.
- **PMC9327140** — protocol for a systematic review / network meta-analysis of
  rodent ASD behavioral phenotypes. Targets Ube3a, Pten, Nlgn3, Shank3, Mecp2,
  Fmr1, but its supplements are methodology only (search syntax, phenoterms),
  no per-gene data. Watch for the completed meta-analysis, which may release an
  extraction table.
- **Keypoint-MoSeq** — Weinreb et al. 2024, *Nature Methods*. Unsupervised
  behavioral-syllable method (MoSeq4all.org); code + demo data only, no per-gene
  panel. A method to mine for specific NDD-gene MoSeq studies later.

---

## Suggested prioritization

1. **IMPC (B1) + AutDB / Das 2019 (B2)** — the two per-gene behavioral
   databases; together they give quantitative KO phenotypes (IMPC) and curated
   ASD-gene behavioral annotations (AutDB). Highest expected value.
2. **Kumar Sheppard 2022 (B6)** — named ASD mutants (Mecp2 / Fmr1 / Shank3 /
   Cntnap2) *and* a clean MPD deposit; best single-paper behavioral fit.
3. **MPD (B3) + MGI reports (B4)** — the plumbing under much of the above;
   ingest once, reuse for many strain/gene lookups.

Lower expected value but worth filing so the wrangler team can pick them up:

- Kumar grooming (B5) and JABS (B7) — per-strain machine-vision behavior;
  B7 needs table-reduction work first.
- USV models (Tier B3) — only after a supplement/deposit check confirms a
  machine-readable per-gene table exists.
