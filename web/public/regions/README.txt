Brain-region drawings for /regions
==================================

Provenance
----------
human-lateral.svg, human-medial.svg, mouse-sagittal.svg, zebrafish-larva.svg
are PLACEHOLDER schematics hand-authored for SSPsyGene from scratch (Bezier
outlines and straight lobe boundaries). They are not traced from or derived
from any atlas, plate or third-party drawing (no Allen Institute, Gray's
Anatomy or SciDraw source), so they need no credit line. They are not to scale
and not anatomically exact; the page labels them "schematic".

When a drawing is replaced by real atlas geometry, record here: source URL,
version, licence, the credit line shown under the drawing, and how the file
was converted.

Contract for a drawing file (what the page relies on)
-----------------------------------------------------
- A standalone <svg> with a viewBox. Any shapes, groups, clip paths.
- Every clickable region is an element with data-region="<key>", where <key>
  is a region key of that species in web/lib/brain-regions.ts (REGIONS). Several
  elements may share a key (e.g. a region split into polygons); they colour,
  hover and select together. Elements without data-region are decoration.
- Decoration that should let the pointer through to a region underneath
  carries pointer-events="none".
- Optional labels: <text data-label-for="<key>">Name</text>. The page appends
  the dataset count. data-ink="auto" switches the text to white on dark fills
  (for labels drawn inside their region).
- No scripts, no external references (the file is inlined into the page).

Plugging in a new drawing
-------------------------
1. Put the SVG here, with data-region attributes as above (for an Allen
   reference-atlas SVG or ggseg polygons, map each structure to a region key —
   add new keys to REGIONS if the drawing is finer than today's map).
2. Register it in web/lib/region-drawings.ts (species, view key, title, src,
   orientation caption).
3. If it introduces new regions, add RegionDefs (UBERON id, match terms,
   within terms) to REGIONS, and Brodmann-style fixes to CURATED_PART_OF.
4. `npx vitest run lib/__tests__/brain-regions.test.ts` checks every
   data-region key exists in REGIONS and every region is drawn somewhere.
Nothing in the page, the panel, the tray or the API depends on the paths.
