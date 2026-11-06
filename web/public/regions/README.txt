Brain-region drawings for /regions
==================================

Provenance (full download + conversion recipe: data/regions/makeDoc.txt)
------------------------------------------------------------------------
mouse-sagittal.svg
    Allen Mouse Brain Atlas, P56 sagittal reference atlas (atlas id 2),
    section 172 (sub-image 100883804), structure-boundary graphics (group 28),
    downloaded from api.brain-map.org svg_download. Allen's polygons are kept
    as is (coordinates rounded, uniformly scaled); each is tagged with its
    Allen structure and merged into a region by
    web/lib/regions/allen-mouse-regions.json. Allen Institute Terms of Use;
    credit shown under the drawing: "Image credit: Allen Institute"
    (https://alleninstitute.org/citation-policy/).
human-lateral.svg, human-medial.svg
    ggsegDKT 2.0.1 (Desikan-Killiany-Tourville atlas; Klein & Tourville 2012),
    CC0, https://github.com/ggseg/ggsegDKT . Left-hemisphere lateral and
    right-hemisphere medial views; DKT parcels grouped into lobes by
    web/lib/regions/dkt-lobes.json.
zebrafish-larva.svg
    PLACEHOLDER schematic, hand-drawn for SSPsyGene; no source.

Contract for a drawing file (what the page relies on)
-----------------------------------------------------
- A standalone <svg> with a viewBox. Any shapes, groups, transforms, clip paths.
- Every clickable region is an element with data-region="<key>", where <key>
  is a region key of that species in web/lib/brain-regions.ts (REGIONS). Many
  elements may share a key (e.g. a region made of several atlas structures);
  they colour, hover and select together. Elements without data-region are
  decoration.
- Optional data-outline="<key>" element: the region's merged outline, used
  for the selection / in-vitro rings instead of every piece.
- Optional data-region-stroke="fill" on the root: piece boundaries inside a
  region are hidden (stroked in the fill colour); use with data-outline.
- Decoration that should let the pointer through carries
  pointer-events="none".
- Optional labels: <text data-label-for="<key>">Name</text>. The page appends
  the dataset count; data-ink="auto" switches to white on dark fills.
- No scripts, event handlers or external references (the file is inlined
  into the page; the tests check this).

Plugging in a new drawing
-------------------------
1. Put the SVG here following the contract (for atlas geometry, tag each
   structure with data-region via a hand-curated structure -> region map,
   as allen-mouse-regions.json / dkt-lobes.json do).
2. Register it in web/lib/region-drawings.ts (species, view key, label,
   title, src, caption, credit).
3. New regions: add RegionDefs (UBERON id, match / exact terms, within
   terms) to REGIONS in web/lib/brain-regions.ts.
4. Record the download and conversion in data/regions/makeDoc.txt.
5. `npx vitest run lib/__tests__/brain-regions.test.ts` checks every
   data-region key exists, every region is drawn, and the files are safe.
Nothing in the page, the panel, the tray or the API depends on the paths.
