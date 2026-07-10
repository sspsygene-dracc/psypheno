# Candidate BEHAVIORAL studies for psypheno ingestion

A follow-up to [`candidate-studies.md`](candidate-studies.md), which was geared
toward high-throughput molecular data (RNA-seq, scRNA-seq, CRISPR screens,
GWAS/exome per-gene tables). This memo deliberately **de-emphasizes omics** and
surfaces **behavioral** and **in-vivo neurophysiological** readouts — mouse
phenotyping batteries, decision-making / computational-psychiatry assays,
ultrasonic vocalization, machine-vision behavior, and human behavioral
instruments — in neurodevelopmental / autism / neuropsychiatric contexts.

Two ingest models are represented here, and they have **different** data
requirements:

1. **Gene → phenotype linkage (studies below).** A curated association between a
   named risk gene (and its mouse/rat model) and a described behavioral, neural,
   or computational phenotype. The quantitative values are often buried in a
   paper's text/figures rather than a supplement — **that is fine**; the
   linkage is the ingestible unit. This is the model behind studies like Noel
   et al. 2025 (*Nat Neurosci*, the exemplar the wrangler team flagged).
2. **Bulk / downloadable behavioral tables (databases at the end).** Consortium
   or curated databases (IMPC, AutDB/SFARI, MPD, MGI) that expose behavioral
   readouts already keyed to genes or strains in machine-readable bulk exports.

Provenance: reconstructed from two deep-research literature sweeps (fetched
primary sources, adversarially verified claims). Items marked **[verified]**
were fetch-checked and passed adversarial verification; items marked
**[snippet]** come from search results and are reliable on the *phenotype* but
their **citation details (DOI / PMID / year) should be confirmed before
ticketing**. Preprints are marked **[preprint]** — per project guidance we lean
toward journal-published work, so treat those as watch-items.

---

# PART A — Studies (gene → phenotype linkage)

## A1. Cross-genotype convergence studies

The design the wrangler team most wants: multiple ASD/NDD-gene mouse lines run
through the *same* assay to find a convergent phenotype.

### Noel et al. 2025 — common computational/neural anomaly across ASD models *(the exemplar)* [verified]
- *Nature Neuroscience* **28**, 1519–1532 (2025). PMID 38766250 /
  doi:10.1038/s41593-025-01965-8.
- **Genes/models:** *Fmr1*, *Cntnap2*, *Shank3B* mutant mice. **Cross-genotype.**
- **Assay/phenotype:** rodent psychophysics + behavioral modeling + brain-wide
  single-cell (Neuropixels) recordings → all three show a **blunted / inflexible
  update of priors during perceptual decision-making**, with a shared neural
  signature: **prior encoding shifts from sensory to frontal cortex**, and
  frontal units over-represent deviations from the animal's long-run prior.
  Mouse.

### Hsu et al. 2025 — whole-brain connectivity + sensory deficits across ASD models [verified]
- *Molecular Psychiatry* (2025). doi:10.1038/s41380-025-03340-2 / PMID 41266875.
- **Genes/models:** *Tbr1*⁺ᐟ⁻, *Nf1*⁺ᐟ⁻, *Vcp*⁺ᐟᴿ⁹⁵ᴳ (reviews Cntnap2, En2,
  Fmr1, Gabrb3, Mecp2, Shank2, Shank3, Syngap1). **Cross-genotype.**
- **Assay/phenotype:** AI whole-brain mapping (BM-auto, Thy1-YFP) + olfactory
  discrimination + social behavior → **piriform cortex is the only region
  consistently impaired across all three lines**; all three share an
  **olfactory-discrimination deficit** (divergent somatosensory signatures).
  Mouse. *Vcp⁺ᐟᴿ⁹⁵ᴳ is a knock-in point mutant, not a null.*

### Kloth et al. 2015 — cerebellar associative sensory learning defects in five ASD models [snippet]
- "Cerebellar associative sensory learning defects in five mouse autism models"
  (*eLife*, ~2015). PMC4512177.
- **Cross-genotype** (five ASD lines) on one eyeblink-conditioning assay →
  **shared cerebellar learning-timing deficit**. Predates the 2018+ window but
  is a canonical convergence design. Mouse.

### Cortical development dynamics across ASD mouse models — Nature 2026 [snippet]
- doi:10.1038/s41586-026-10679-1 (2026).
- **Cross-genotype** developmental transcriptomic-electrophysiological pipeline
  → **convergent stage-bound programs** (delayed radial-glia progression, early
  postnatal ion-channel / synaptic downregulation) with genotype-specific
  signatures intensifying with maturation. Neural-heavy; behavioral component
  thinner than Noel. Mouse. **Confirm citation before ticketing.**

## A2. Computational-psychiatry: decision-making, prior/belief updating, reinforcement learning

The closest single-gene analogues to Noel 2025 — Bayesian belief-updating,
prior-weighting, evidence-accumulation, or reinforcement-learning constructs
paired with in-vivo physiology.

### Scn2a⁺ᐟ⁻ — flexible decision-making + in-vivo dendritic imaging *(strongest single-gene match)* [verified]
- Bender lab (UCSF). *PNAS* **122** (2025). doi:10.1073/pnas.2508836122 /
  PMID 41264237 / PMC12646510.
- **Gene/model:** *Scn2a* haploinsufficiency (high-confidence ASD gene).
  Single-gene.
- **Assay/phenotype:** matching-pennies competitive task → **inflexible under
  changing competitive pressure**; 2-photon Ca²⁺ imaging of apical/proximal
  dendrites in medial frontal cortex pyramidal cells shows **diminished
  apical-proximal coupling** and altered tuft encoding of reward/strategy.
  Mouse.

### Grin2a Y700X — Bayesian belief-updating + mediodorsal thalamus [verified]
- *Nature Neuroscience* (2026). doi:10.1038/s41593-026-02237-9 (bioRxiv
  2024.01.08.574745).
- **Gene/model:** *Grin2a* patient-derived knock-in (Y700X⁺ᐟ⁻). Single-gene.
  **Framed as schizophrenia-risk** (GRIN2A / SCHEMA) — also a recognized NDD
  gene, but not classically autism.
- **Assay/phenotype:** dynamic foraging + explicit Bayesian model → **slower
  belief-update rate, over-weights prior, unstable behavioral states**;
  functional ultrasound flags **mediodorsal thalamus hypofunction**; MD
  optogenetic inhibition phenocopies, enhancement rescues. Mouse.

### Nrxn1α KO — IBL prior-weighting task + widefield imaging *(tightest topical match)* [verified] [preprint]
- Davatolhagh, Couto, Melin, Oesch, Findling et al. (Churchland lab / IBL).
  bioRxiv 2025.09.12.675910.
- **Gene/model:** *Nrxn1α* (Neurexin-1α) KO. Single-gene.
- **Assay/phenotype:** the exact IBL two-choice prior-weighting task +
  cortex-wide widefield Ca²⁺ → **underuses priors, slow to update on feedback,
  over-relies on sensory input; cortex-wide activity elevated + more
  correlated.** Explicitly frames itself as convergent with Noel's
  Fmr1/Cntnap2/Shank3B. Mouse. *Nrxn1α isoform KO, not full null; widefield,
  not Neuropixels.*

### Tsc2 + Shank3B — reinforcement-learning modeling, cross-genotype [snippet] [preprint]
- bioRxiv 2025.01.15.633099 / PMC11760717.
- **Genes/models:** *Tsc2*⁺ᐟ⁻ and *Shank3B*⁺ᐟ⁻. **Cross-genotype.**
- **Assay/phenotype:** odor-based 2AFC fit with an RL model → both converge on
  an **enhanced positive learning rate, male-only, early adolescence.** Mouse.

### Tsc1 (cerebellar Purkinje) — sensory evidence-accumulation task [snippet] [preprint]
- bioRxiv 2021.12.23.474034.
- **Gene/model:** *Tsc1*, L7-Cre Purkinje-specific. Single-gene.
- **Assay/phenotype:** sensory **evidence-accumulation** task + in-vivo
  Purkinje-cell recording → **accelerated learning + enhanced sensory
  salience.** Mouse.

### 16p11.2 hemideletion — reward learning (Grissom 2018) [snippet]
- Grissom et al. *Molecular Psychiatry* (2018). PMID 29038598.
- **Model:** 16p11.2 CNV deletion. **Assay/phenotype:** operant reward-directed
  learning → **male-specific reward-learning impairment + reduced motivation**,
  tied to striatal dysfunction. Mouse. (See also A5 for other 16p11.2 papers.)

## A3. Cognitive flexibility & reversal learning (single-gene)

Reversal-learning / flexibility deficits — the "inflexible updating" construct
Noel 2025 formalizes — cleanly attributed to canonical genes.

### Cntnap2⁻ᐟ⁻ — striatal hyperexcitability + reversal inflexibility [verified]
- *eLife* (2024), art. 100162. PMID 38766169 / doi:10.7554/eLife.100162.
- **Gene/model:** *Cntnap2* KO (canonical ASD gene). Single-gene.
- **Assay/phenotype:** four-choice odor reversal-learning task → **reversal
  deficit with perseverative errors**; whole-cell patch clamp shows
  direct-pathway striatal projection neurons with **increased intrinsic
  excitability** via altered Kv1.2 (Caspr2 organizes Kv1.2 clustering). Mouse.

### Fmr1 KO — probabilistic reversal learning, cross-species [snippet]
- PMID 36688132 / PMC9849779.
- **Gene/model:** *Fmr1* KO paired with human Fragile-X data. **Assay/phenotype:**
  probabilistic (stochastic-reward) reversal → **male KO impaired on initial
  probabilistic learning + reversal; females selectively impaired on
  reversal.** Mouse + human. Amenable to RL / belief-updating decomposition.

### Fmr1 KO — reversal-learning flexibility deficit [snippet]
- *F1000Research* (2018). PMID 30057755 / PMC6051189.
- **Gene/model:** *Fmr1* KO. **Assay/phenotype:** males acquire the initial rule
  normally but are **selectively impaired at the reversed contingency**,
  isolating a flexibility/updating deficit. Mouse.

### Grin2a — cognitive flexibility via LC→mPFC modulation [snippet] [preprint]
- bioRxiv 2025.02.01.636062.
- **Gene/model:** *Grin2a*. **Assay/phenotype:** **cognitive-flexibility /
  reversal deficit** via disrupted locus-coeruleus modulation of prefrontal
  circuits (prefrontal gamma coordination). Mouse.

### Shank2 KO — valence-dependent reversal deficit [snippet]
- *Molecular Autism* (2022). PMC9531513.
- **Gene/model:** *Shank2* KO. **Assay/phenotype:** males show **impaired
  reversal only under aversive (air-puff) outcomes** plus heightened
  anticipatory aversive responses; intact under reward-only. Mouse.

## A4. Single-gene in-vivo circuit physiology & neural coding

Named-gene → circuit/coding phenotypes with in-vivo electrophysiology, calcium
imaging, or functional ultrasound (less computational-psychiatry framing than
A2, but rich physiology).

### Cntnap2 — reticular thalamic hyperexcitability drives ASD behaviors [snippet]
- *Science Advances*. doi:10.1126/sciadv.adw4682.
- **Gene/model:** *Cntnap2* KO. **Phenotype:** **reticular-thalamic
  hyperexcitability** drives ASD-like behaviors (gene → circuit → behavior).
  Mouse.

### Cntnap2 — impaired emotion recognition + PFC hyper-synchrony [snippet]
- *Molecular Psychiatry* (2024). doi:10.1038/s41380-024-02754-8.
- **Gene/model:** *Cntnap2*-deficient. **Phenotype:** social/emotion-recognition
  deficit associated with **hyper-synchronous prefrontal cortex activity**
  (in-vivo PFC recordings; frontal angle parallels Noel). Mouse.

### Cntnap2 — degraded tactile cortical coding [snippet]
- PMC10557772 (2023).
- **Gene/model:** *Cntnap2*. **Phenotype:** in-vivo somatosensory cortex
  recordings → **degraded / less-reliable tactile stimulus representations**
  (sensory-prior relevance). Mouse.

### Scn2a⁺ᐟ⁻ — cortico-collicular feedback failure / context processing [snippet]
- PMC12484672 (2025).
- **Gene/model:** *Scn2a*. **Phenotype:** in-vivo recordings show
  **cortico-collicular feedback failure** degrading context-dependent sensory
  processing (predictive-coding angle; complements the PNAS Scn2a decision
  paper in A2). Mouse.

### Tsc1 (Purkinje-specific) — sex-specific behavior + Purkinje physiology [snippet]
- *Frontiers in Behavioral Neuroscience* (2024).
- **Gene/model:** *Tsc1*, Purkinje-specific deletion. **Phenotype:** autism
  behavior battery (social, repetitive, vocalization) + reduced simple/complex
  Purkinje-spike firing in awake animals; **sex-by-genotype interaction.**
  Mouse.

## A5. Copy-number-variant models (16p11.2, 22q11.2)

### 16p11.2 deletion — basal-ganglia circuit + reward learning [snippet]
- Portmann et al. *Cell Reports* (2014).
- **Phenotype:** reward-learning deficits, hyperactivity, movement-control
  problems tied to **excess Drd2⁺ striatal MSNs** + slice-ephys synaptic
  defects. Mouse.

### 16p11.2 deletion — PFC NMDAR deficits, chemogenetically rescued [snippet]
- *J. Neurosci.* (2018). PMC6021990.
- **Phenotype:** **39–52% reduced NMDAR-EPSCs in mPFC** + behavioral deficits,
  both rescued by chemogenetic PFC activation (causal frontal-circuit link).
  Mouse.

### 16p11.2 deletion — fronto-temporal connectivity + attention [snippet]
- PMC10209099.
- **Phenotype:** **paradoxically enhanced attentional ability** with
  fronto-temporal functional-connectivity + GABAergic dysfunction. Mouse.

### 22q11.2 deletion (Df(16)A⁺ᐟ⁻) — impaired hippocampal place-cell dynamics [snippet]
- PMC5763006.
- **Phenotype:** reduced spatial-map stability + absence of goal-directed
  place-cell reorganization during learning (circuit-level cognitive-flexibility
  readout). Mouse.

## A6. Machine-vision behavioral genetics (Vivek Kumar lab, JAX)

Per-**strain** machine-vision behavior; several include named ASD/NDD mutant
lines and QTL→gene mapping. Structured data is additionally downloadable (Mouse
Phenome Database, Zenodo, Harvard Dataverse) — hub: kumarlab.org/resources.

### Geuther et al. 2021 — automated grooming (repetitive behavior) [snippet]
- *eLife* **10**, e63207 (2021). doi:10.7554/eLife.63207.
- **Assay/phenotype:** NN-scored grooming quantity + patterning + open-field
  anxiety/activity across 2,457 mice, 62 strains; GWAS → **130 QTL** mapping to
  neurodev genes incl. **Sox5, FoxP1, Ctnnb1, Grin2b.** Data in MPD project
  Kumar3; Suppl. file 2 = gene table; Zenodo 10.5281/zenodo.4646088. Mouse.

### Sheppard et al. 2022 — stride-level gait [snippet]
- *Cell Reports* **38**, 110231 (2022). doi:10.1016/j.celrep.2021.110231 /
  PMID 35021077.
- **Assay/phenotype:** 14 gait/posture metrics via deep-learning pose
  estimation across 62 strains — **plus ASD/NDD mutants Mecp2, Fmr1, Shank3,
  Cntnap2, Del4Aam** (+ SOD1-G93A, Ts65Dn). Data in MPD project Kumar4; Zenodo
  10.5281/zenodo.5708437; GitHub KumarLabJax. Mouse.

### JABS — JAX Animal Behavior System (2025) [snippet]
- *eLife* **14**, e107259 (2025) (successor to a 2022 bioRxiv preprint).
- **Assay/phenotype:** grooming, posture, gait, turning, rearing, scratching,
  escape + higher-order constructs (biological age, pain, seizure) across ~168
  strains, with heritability + GWAS. Datasets JABS600 / JABS1200 / JABS-BxD on
  Harvard Dataverse (doi:10.7910/DVN/SAPNJG, 10.7910/DVN/RQYI04). Mouse. *Video
  + keypoint deposits, not a tidy per-gene CSV — needs table-reduction.*

## A7. Ultrasonic vocalization gene models

Per-genotype USV phenotyping of named genes. Under the gene→phenotype ingest
model these are viable even though the quantitative values sit in the paper's
figures/tables rather than a supplement — confirm the phenotype direction before
ticketing.

### Crmp4 / Dpysl3 KO — male-predominant USV phenotype [snippet]
- PMC9139187.
- **Gene/model:** *Crmp4/Dpysl3* KO vs WT littermates. **Phenotype:**
  isolation-induced calls in 10 call types, **per-genotype × per-sex counts**;
  male-predominant. Mouse.

### NS-Pten KO — sex- and age-specific USV differences [snippet]
- PMC5698873.
- **Gene/model:** neuron-subset *Pten* KO (PTEN is an ASD gene). **Phenotype:**
  PND8/PND11 isolation USVs → **per-genotype call counts, duration, peak
  amplitude with sex and age effects.** Mouse.

## A8. Human behavioral cohorts (deeply phenotyped, access-gated)

Human per-individual / per-gene-condition behavioral phenotyping. Rich but
**gated behind a SFARI Base data-use agreement**, not open downloads.

### Simons Simplex Collection (SSC) + SPARK [verified]
- SFARI resources, via SFARI Base (base.sfari.org).
- **Phenotypes:** SCQ-Lifetime, Repetitive Behavior Scale-Revised, CBCL 6-18,
  ADOS/ADI-R, IQ; per-individual, per-gene-condition. Human. **Access-gated.**

### Litman et al. 2025 — decomposition of ASD phenotypic heterogeneity [verified]
- PMC12283356 (2025).
- **Cohorts:** SPARK (n=5,392) + SSC (n=861), 239 behavioral features across 7
  categories. Raw phenotype data gated; **Supplementary Data 1 CSV is
  ASD-relevant gene *sets*** (not per-gene behavioral readouts). Code:
  github.com/FunctionLab/asd-pheno-classes; Zenodo 10.5281/zenodo.15324658.
  Human.

---

# PART B — Database resources (downloadable per-gene / per-strain behavioral data)

Consortium/curated databases that expose behavioral readouts already keyed to
genes or strains in machine-readable bulk exports. These are the ingest targets
when you want quantitative per-gene/per-strain tables rather than a single
paper's gene→phenotype claim.

## B1. IMPC — International Mouse Phenotyping Consortium [verified]
- Groza et al. 2023, *Nucleic Acids Research* **51**, D1038. PMID 36305833 /
  doi:10.1093/nar/gkac972. Portal: Koscielny et al. 2014, *NAR* **42**, D802
  (PMID 24194600).
- **Behavioral phenotypes:** standardized behavioral/neurological pipeline —
  open field (anxiety/exploration/activity), acoustic startle & PPI, grip
  strength, SHIRPA.
- **Model / scale:** mouse single-gene knockouts. **DR24 (Mar 2026): 9,605 KO
  genes, 10,341 lines, 138M+ data points, 111,664 statistically significant
  per-gene phenotype calls.**
- **Downloadable:** REST/Solr API, bulk FTP dumps (parquet/CSV) per release, and
  a batch-query tool at mousephenotype.org. Consortium-generated,
  **already gene-mapped with statistical calls** — the cleanest per-gene
  behavioral source. Mouse.

## B2. AutDB / SFARI Gene Animal Model module — Das et al. 2019 [verified]
- *Molecular Autism* **10**, 11 (2019). doi:10.1186/s13229-019-0263-7 /
  PMC6417187.
- **Behavioral phenotypes:** phenoterm/phenovalue annotations (Increased /
  Decreased / Abnormal / No Change) across **450+ paradigms** — social
  interaction, ultrasonic vocalization, repetitive behavior, anxiety, seizures,
  motor, learning/memory.
- **Model / scale:** **258 ASD-linked genes, 6 CNV regions, 72 environmental
  inducers, 9 inbred strains, curated from 787 publications.** Shank3 case study
  annotates 27 loss-of-function models separately (15 KO + 10 KI mouse, 2 KO
  rat).
- **Downloadable:** supplementary tables S1–S9 (.xlsx/.docx); full dataset in
  AutDB (autism.mindspec.org/autdb, mirrored at gene.sfari.org/autdb). Mouse
  (+ rat).
- **Caveat:** the SFARI Gene animal-models *landing-page* CSV
  (`download-csv.php?api-endpoint=animal-genes`, ~269 models) has **only summary
  fields**, not the behavioral readouts — ingest from the Das supplement / AutDB
  / gene pages, not the landing CSV.

## B3. Mouse Phenome Database (MPD) [verified]
- Bogue et al. 2020, *NAR* **48**, D716. PMID 31696236. phenome.jax.org (JAX).
- **Behavioral phenotypes:** curated strain-survey behavior — open-field
  thigmotaxis/anxiety, activity, sociability, behavioral despair, grooming
  ("Behavior tests" is a first-class category).
- **Model / scale:** 2,000+ mouse strains/populations (inbred, CC, DO,
  transgenic). Per-**strain** (maps to genetic background), not per-gene-KO.
- **Downloadable:** bulk CSV/CSV.GZ at phenome.jax.org/downloads
  (`strainmeans.csv.gz`, `animaldatapoints.csv.gz` = one row/animal,
  `measurements.csv`, `straininfo.csv`) + JSON/CSV API. **Hosts the Kumar lab
  datasets (projects Kumar3, Kumar4) from A6.** Mouse.

## B4. MGI Mammalian Phenotype Ontology gene→phenotype reports [verified]
- Mouse Genome Informatics, informatics.jax.org. Ongoing resource.
- **Behavioral phenotypes:** MP-ontology categorical annotations under the
  "abnormal behavior" / "nervous system phenotype" branches.
- **Model:** mouse genes/alleles. **The most directly per-gene-mappable**
  resource here.
- **Downloadable:** flat TSV report files (`MGI_GenePheno.rpt`,
  `MGI_PhenoGenoMP.rpt`) linking genes/alleles → MP behavioral terms; MouseMine
  programmatic access. Categorical (annotation), not quantitative. Mouse.
