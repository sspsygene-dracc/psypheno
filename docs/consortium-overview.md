# SSPsyGene consortium — project background & the collated overview table

Context doc for people (and agents) working on **Psypheno**, the public website
at https://psypheno.gi.ucsc.edu/. It explains what the **SSPsyGene** consortium
is, why the data on the site is shaped the way it is, and what the *collated
cross-modality overview table* (the "overview matrix") is meant to show. Nothing
here is code reference — for that, see `docs/development.md`,
`docs/adding-datasets.md`, and `docs/server-architecture.md`.

## Overview

**SSPsyGene** is a research **consortium**: many independent labs, each with its
own experimental speciality, that agreed to study the *same* set of genes in
*comparable* ways. Rather than every group pursuing its own gene list and its own
protocols, the consortium collectively:

- selected a shared panel of **~250 priority neuropsychiatric genes** (the
  "SSPsyGene 250"), and
- committed to a set of **standardized mouse strains and protocols**, so that a
  result produced by one group can be lined up against a result from another.

Roughly **~70 of the ~250 genes have knockout mouse models**, which is what makes
the in-vivo modalities (behavior, morphology, electrophysiology) possible for
those genes.

The point of all this standardization is a single scientific goal: build a
**comparable map of what each of these genes does** — across expression,
behavior, morphology, physiology, and perturbation readouts — and then use that
map as the substrate for follow-on mechanistic work. Psypheno is where that map
is assembled and displayed.

## Why comparability is the whole game

A consortium is only more than the sum of its labs if the results can be
*combined*. Two labs measuring "the effect of knocking out gene X" are only
comparable if they used compatible strains, compatible assays, and compatible
analysis. The shared gene panel + shared protocols are what let Psypheno do
things a single-lab dataset never could — most visibly the **cross-study
meta-analysis** (`/most-significant`), which combines per-gene p-values across
studies, and the **collated overview table** described below.

## The modalities

Each consortium group tends to specialize in one or a few **modalities** —
experimental readout types. These are the **columns** of the overview matrix. The
whiteboard sketch listed seven; the shipped taxonomy has **six** (the standalone
FISH column was dropped — see below):

| Modality | What it measures | Maps to `assayTypes` | Always shown |
|---|---|---|---|
| **RNA expression** | Bulk / single-cell differential expression | `expression` | — |
| **Behavioral** | Standardized behavioral assays on KO mice (incl. USV, machine-vision) | `behavior` | ✓ |
| **Morphology** | Cell / tissue morphology phenotypes | *(none yet)* | ✓ |
| **Electrophysiology** | Neuronal physiology / firing properties | *(none yet)* | ✓ |
| **Perturb-seq** | Pooled CRISPR perturbation + sequencing readouts (DEGs, GRN, cell-proportion, splicing) | `perturbation_deg` + `perturbation` | — |
| **Perturb-FISH** | Pooled perturbation + spatial FISH readout, across cell types | `spatial` | — |

The canonical machine vocabulary lives in `data/datasets/globals.yaml` under
two blocks: `assayTypes` (`expression, spatial, behavior, perturbation,
perturbation_deg, curated, phenotype`) is the per-dataset assay tag, and the
newer `modalities:` block is the **overview-table column taxonomy** built on top
of it. The modality list is a **superset** of the assay vocabulary — it renames
assay keys to user-facing labels and adds **morphology** and
**electrophysiology**, which have no assay type and no data yet (empty
`alwaysShow` placeholders). Three deliberate reconciliations, confirmed with the
maintainer, shape the mapping:

- **No standalone FISH column.** The matrix is perturbation-centric (rows =
  perturbed genes). Pure FISH is `spatial` with only *target*-direction links,
  so it produces no perturbed-gene rows; only **perturb-FISH** (a `spatial` table
  with a *perturbed*-direction link) does. A standalone FISH column would always
  be empty here, so it's omitted and can return if non-perturbation spatial data
  ever lands.
- **`curated` / `phenotype` are excluded.** Those datasets (ClinVar, SFARI,
  GeneTrek, Satterstrom, MGI phenotypes) are external annotation databases, not
  SSPsyGene consortium experiments, so they aren't modality columns.
- **Generic `perturbation` folds into Perturb-seq.** The non-DEG, non-spatial
  perturbation readouts — GRN edges, cell-proportion shifts, splicing — join the
  Perturb-seq column so every perturbation table appears somewhere. Net: `spatial`
  → perturb-FISH, every other perturbation assay → perturb-seq.

This config-driven taxonomy (leaf #211 of the epic) is the shared axis the rest
of the overview-table feature queries — see the epic.

## The collated overview table

The overview table is a **matrix**:

- **rows** = **perturbed genes** (a gene that was knocked out / knocked down in
  some experiment), and
- **columns** = **modalities** (the readout types above).

Each cell answers: *for this gene, in this modality, what do we know?* In the
first version a cell is a **status glyph** — significant result / data present
but not significant / assayed but null / no data — and clicking a cell drills
into the underlying rows (the DEG list, the screen hits) for that gene and
modality. It is an **overview of the consortium's research results**, not a
single dataset.

### Gaps are permanent and expected

There will **never** be a "complete" overview table. Not every group runs every
assay on every gene: one lab may do behavior on a handful of genes that no other
lab touches; morphology may only ever exist for the genes with KO models; some
combinations will simply never be measured. So the UI is built around **gaps as a
first-class state**:

- Missing cells are shown as gaps, not errors or zeros.
- **"Expensive," low-output modalities** — behavior, morphology,
  electrophysiology — are shown **even when entirely empty**, because a
  *not-yet-run* expensive assay is itself informative (it tells the consortium
  where to invest). These columns are always present.
- Some gaps will fill as more data lands; some never will. That's the intended
  steady state, not a defect.

## Current coverage (as of mid-2026)

Most of what exists today is on the RNA / perturbation side:

- **~199 perturbed genes** across **7 perturbation DEG / screen tables**
  (source datasets include `mouse-perturb-4tf`, `perturb-fish`,
  `ding-cortical-tf-crispri`, `hsc-autism-organoid-m5`, `polygenic-risk-20`, plus
  non-meta perturbation datasets `fernando-2025`, `fleck-organoid-grn`,
  `dynamic_convergence`).
- **Behavioral, morphology, and electrophysiology data are not in yet.**
  Behavioral data may arrive soon; in the meantime we may add a few
  non-SSPsyGene publications purely to exercise the UI. The overview table is
  built data-driven, so rows and filled cells appear automatically as those
  datasets land.

## Paper context

The consortium PIs want an integrated, consortium-wide view of the results, and a
paper showing integrated cross-modality analysis is planned within a couple of
months (targeting roughly autumn 2026). The overview table is the first concrete
step toward that: get the data into a comparable matrix form, display it well,
and decide where to take the integrated analysis from there.

## Pointers into the code

- **Perturbed vs. target direction** is encoded in `data_tables.link_tables`
  (`"column:link_table:direction"`, where direction is `perturbed` or `target`).
  The perturbed link tables `{table}__{link}` join `central_gene_id` →
  `central_gene`; that join is how "every gene perturbed in some dataset" (the
  matrix rows) is derived — no schema change needed.
- **Assay / modality / condition / organism vocab**: `data/datasets/globals.yaml`.
- **Cross-dataset assembly pattern**: `web/pages/api/gene-pair-data.ts` already
  loops all `data_tables` and groups by `assay`; the overview-matrix API is a
  many-gene generalization of it.
- **Per-(gene, table) significance predicate**: `web/pages/api/significant-rows.ts`
  and the meta-analysis `collect_pvalues_for_tables`
  (`processing/src/processing/combined_pvalues/`).
