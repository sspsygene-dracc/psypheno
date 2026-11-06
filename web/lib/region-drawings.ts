// Registry of the /regions drawings. The geometry lives in vendored SVG files
// under web/public/regions/ (provenance and the file contract in
// web/public/regions/README.txt); what each shape *means* lives in
// lib/brain-regions.ts. To swap a drawing for real atlas geometry, replace the
// file (or add one and point `src` at it) — no page code changes.

import type { BrainView } from "@/lib/brain-regions";

export type RegionDrawing = {
  /** ?side= value; also the toggle label when a view has several drawings. */
  key: string;
  label: string;
  /** Accessible title. */
  title: string;
  /** Served path of the SVG (web/public/...). */
  src: string;
  /**
   * The SVG's viewBox width and height (the test checks they match), so the
   * page reserves the drawing's space before the file has loaded.
   */
  viewBox: [number, number];
  /** Caption under the drawing. */
  caption: string;
  /** Credit line required by the drawing's source, shown under it. */
  credit?: { text: string; href: string };
};

// ggsegDKT is CC0 (no credit required); we credit it anyway.
const DKT_CREDIT = {
  text: "Atlas: ggsegDKT (Desikan-Killiany-Tourville; Klein & Tourville 2012), CC0",
  href: "https://github.com/ggseg/ggsegDKT",
};

export const REGION_DRAWINGS: Readonly<Record<BrainView, readonly RegionDrawing[]>> = {
  human: [
    {
      key: "lateral",
      label: "Lateral",
      title: "Human cortex, lateral view of the left hemisphere (DKT atlas)",
      src: "/regions/human-lateral.svg",
      viewBox: [520, 357.1],
      caption:
        "Lateral view, left hemisphere · anterior to the left · DKT cortical parcels (thin lines) grouped into lobes (dark outlines)",
      credit: DKT_CREDIT,
    },
    {
      key: "medial",
      label: "Medial",
      title: "Human cortex, medial view of the right hemisphere (DKT atlas)",
      src: "/regions/human-medial.svg",
      viewBox: [520, 359.7],
      caption:
        "Medial view, right hemisphere · anterior to the left · DKT cortical parcels grouped into lobes; grey = medial wall",
      credit: DKT_CREDIT,
    },
  ],
  mouse: [
    {
      key: "sagittal",
      label: "Sagittal",
      title: "Mouse brain, sagittal section (Allen Mouse Brain Atlas, P56)",
      src: "/regions/mouse-sagittal.svg",
      viewBox: [520, 271.1],
      caption:
        "Allen Mouse Brain Atlas, P56 sagittal reference atlas, section 172 · anterior to the left · Allen structures merged into the regions our datasets are tagged with",
      credit: {
        text: "Image credit: Allen Institute",
        href: "https://alleninstitute.org/citation-policy/",
      },
    },
  ],
};

/** Region keys an SVG drawing marks clickable (its data-region values). */
export function svgRegionKeys(svg: string): string[] {
  return Array.from(new Set(Array.from(svg.matchAll(/data-region="([^"]+)"/g), (m) => m[1])));
}
