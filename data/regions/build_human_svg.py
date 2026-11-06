#!/usr/bin/env python3
"""Build web/public/regions/human-{lateral,medial}.svg from the ggsegDKT atlas.

Input: dkt.json, the atlas' 2D polygons as exported by export_dkt_polygons.R
(see makeDoc.txt). ggsegDKT is CC0 (github.com/ggseg/ggsegDKT).

Views: the left hemisphere's lateral view and the right hemisphere's medial
view, so both have anterior to the left. Each DKT parcel becomes one <path>
with data-region = its lobe (from web/lib/regions/dkt-lobes.json) and
data-dkt = the parcel name. Parcels with no
lobe (the medial wall, "unknown") are drawn grey and not clickable. A merged
outline per lobe (shapely union) is drawn on top, so lobe boundaries read
clearly between the parcel lines.

Usage: build_human_svg.py dkt.json dkt-lobes.json OUT_DIR
Needs shapely (only for the lobe outlines).
"""

from __future__ import annotations

import json
import sys

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

WIDTH = 520.0
PAD = 8.0

VIEWS = {
    # file stem: (ggseg view, hemisphere prefix, title)
    "human-lateral": ("lateral", "lh_", "lateral view of the left hemisphere"),
    "human-medial": ("medial", "rh_", "medial view of the right hemisphere"),
}

LABEL_NAMES = {
    "frontal": "Frontal",
    "parietal": "Parietal",
    "temporal": "Temporal",
    "occipital": "Occipital",
    "cingulate": "Cingulate",
    "insula": "Insula",
}


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def main(argv: list[str]) -> int:
    rows = json.load(open(argv[1]))
    lobes = json.load(open(argv[2]))["lobes"]
    parcel_lobe = {p: lobe for lobe, ps in lobes.items() for p in ps}
    out_dir = argv[3]

    for stem, (view, hemi, title) in VIEWS.items():
        parts = [r for r in rows if r["view"] == view and (r["label"] or "").startswith(hemi)]
        xs = [pt[0] for r in parts for poly in r["polygons"] for ring in poly for pt in ring]
        ys = [pt[1] for r in parts for poly in r["polygons"] for ring in poly for pt in ring]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        k = (WIDTH - 2 * PAD) / (x1 - x0)
        height = (y1 - y0) * k + 2 * PAD

        def tx(pt: list[float]) -> tuple[float, float]:
            # ggseg y points up; SVG y points down.
            return (PAD + (pt[0] - x0) * k, PAD + (y1 - pt[1]) * k)

        def d_of(polys: list) -> str:
            segs = []
            for poly in polys:
                for ring in poly:
                    pts = [tx(p) for p in ring]
                    segs.append("M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts) + "Z")
            return " ".join(segs)

        shapes: dict[str, list] = {}
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(WIDTH)} {fmt(height)}">',
            f"  <!-- ggsegDKT (Desikan-Killiany-Tourville atlas, CC0), {title}.",
            "       Parcels grouped into lobes by web/lib/regions/dkt-lobes.json.",
            "       Built by data/regions/build_human_svg.py (see makeDoc.txt);",
            "       contract in web/public/regions/README.txt. -->",
        ]
        for r in parts:
            parcel = r["label"][len(hemi):]
            lobe = parcel_lobe.get(parcel)
            d = d_of(r["polygons"])
            if lobe:
                lines.append(f'  <path data-region="{lobe}" data-dkt="{parcel}" fill-rule="evenodd" d="{d}"/>')
                for poly in r["polygons"]:
                    rings = [[tx(p) for p in ring] for ring in poly]
                    shapes.setdefault(lobe, []).append(Polygon(rings[0], rings[1:]).buffer(0))
            else:
                lines.append(
                    f'  <path data-dkt="{parcel}" fill="#f3f4f6" stroke="#d1d5db" stroke-width="0.8" '
                    f'fill-rule="evenodd" d="{d}"/>'
                )
        # Lobe outlines on top (pointer passes through to the parcels).
        lines.append('  <g fill="none" stroke="#374151" stroke-width="1.6" stroke-linejoin="round" pointer-events="none">')
        label_at: dict[str, tuple[float, float]] = {}
        for lobe, polys in shapes.items():
            u = unary_union([p.buffer(0.6) for p in polys]).buffer(-0.6)
            geoms = list(u.geoms) if isinstance(u, MultiPolygon) else [u]
            segs = []
            for g in geoms:
                if g.area < 4:
                    continue
                for ring in [g.exterior, *g.interiors]:
                    segs.append("M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in ring.coords) + "Z")
            lines.append(f'    <path data-outline="{lobe}" d="{" ".join(segs)}"/>')
            biggest = max(geoms, key=lambda g: g.area)
            p = biggest.representative_point()
            label_at[lobe] = (p.x, p.y + 4)
        lines.append("  </g>")
        for lobe, (x, y) in label_at.items():
            lines.append(
                f'  <text data-label-for="{lobe}" data-ink="auto" x="{fmt(x)}" y="{fmt(y)}">'
                f"{LABEL_NAMES.get(lobe, lobe)}</text>"
            )
        lines.append("</svg>")
        with open(f"{out_dir}/{stem}.svg", "w") as f:
            f.write("\n".join(lines) + "\n")
        print(stem, len(parts), "parcels", {k: len(v) for k, v in shapes.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
