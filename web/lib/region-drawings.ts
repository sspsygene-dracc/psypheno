// Registry of the /regions drawings. The geometry lives in vendored SVG files
// under web/public/regions/ (provenance and the file contract in
// web/public/regions/README.txt); what each shape *means* lives in
// lib/brain-regions.ts. To swap a drawing for real atlas geometry, replace the
// file (or add one and point `src` at it) — no page code changes.

import type { RegionSpecies } from "@/lib/brain-regions";

export type RegionDrawing = {
  /** ?view= value; also the toggle label when a species has several. */
  key: string;
  label: string;
  /** Accessible title. */
  title: string;
  /** Served path of the SVG (web/public/...). */
  src: string;
  /** Caption under the drawing. */
  caption: string;
};

export const REGION_DRAWINGS: Readonly<Record<RegionSpecies, readonly RegionDrawing[]>> = {
  human: [
    {
      key: "lateral",
      label: "Lateral",
      title: "Human brain, lateral view (left hemisphere)",
      src: "/regions/human-lateral.svg",
      caption: "Lateral view · anterior to the left · schematic placeholder, not to scale",
    },
    {
      key: "medial",
      label: "Medial",
      title: "Human brain, medial view (brainstem and cerebellum removed)",
      src: "/regions/human-medial.svg",
      caption: "Medial view · anterior to the left · schematic placeholder, not to scale",
    },
  ],
  mouse: [
    {
      key: "sagittal",
      label: "Sagittal",
      title: "Mouse brain, sagittal view",
      src: "/regions/mouse-sagittal.svg",
      caption: "Sagittal section · anterior to the left · schematic placeholder, not to scale",
    },
  ],
  zebrafish: [
    {
      key: "larva",
      label: "Larva",
      title: "Zebrafish larva, lateral view",
      src: "/regions/zebrafish-larva.svg",
      caption: "Lateral view · anterior to the left · schematic placeholder, not to scale",
    },
  ],
};

/** Region keys an SVG drawing marks clickable (its data-region values). */
export function svgRegionKeys(svg: string): string[] {
  return Array.from(new Set(Array.from(svg.matchAll(/data-region="([^"]+)"/g), (m) => m[1])));
}
