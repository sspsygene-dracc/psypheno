// Feature switches, fixed at build time (NEXT_PUBLIC_* is inlined into both
// the server and the client bundles by `next build` / `next dev`).
//
// The brain-region navigator (/regions, /api/region-genes, /api/gene-regions)
// is a discussion prototype: off unless the build sets
// NEXT_PUBLIC_SSPSYGENE_REGIONS=1. Deployed instances don't set it, so the
// page 404s and the header link is hidden there.
export const REGIONS_ENABLED = process.env.NEXT_PUBLIC_SSPSYGENE_REGIONS === "1";
