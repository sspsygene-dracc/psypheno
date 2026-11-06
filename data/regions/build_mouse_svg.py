#!/usr/bin/env python3
"""Build web/public/regions/mouse-sagittal.svg from an Allen reference-atlas SVG.

Input: one sagittal section of the Allen Mouse Brain Atlas (P56) as downloaded by
data/regions/makeDoc.txt (svg_download, graphic group 28 = structure
boundaries), plus the structure ontology (structure graph 1).

The output keeps Allen's polygons unchanged apart from coordinate rounding and
a uniform scale; it only adds attributes:
  data-region       /regions mouse region key (web/lib/regions/allen-mouse-regions.json)
  data-allen-id     Allen structure id
  data-allen-acronym, data-allen-path   for traceability and the tests
Structures no rule claims are drawn grey and are not clickable. Label
positions are placed by hand (LABELS below) after looking at the result.

Usage:
  build_mouse_svg.py SECTION.svg structures.json allen-mouse-regions.json OUT.svg [--report]
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET

WIDTH = 520.0  # output viewBox width (same scale as the other drawings)

# (x, y) in output units; "outside" labels get dark ink and a leader line to
# the given point. Placed by eye for section 100883867.
LABELS: dict[str, dict] = {
    "cortex": {"x": 60, "y": 40, "outside": True, "to": (130, 80)},
    "olfactory_bulb": {"x": 4, "y": 238, "anchor": "start", "outside": True, "to": (50, 205)},
    "hippocampus": {"x": 262, "y": 14, "outside": True, "to": (262, 92)},
    "striatum": {"x": 140, "y": 264, "outside": True, "to": (182, 205)},
    "thalamus": {"x": 268, "y": 140},
    "hypothalamus": {"x": 262, "y": 264, "outside": True, "to": (235, 215)},
    "midbrain": {"x": 352, "y": 112},
    "cerebellum": {"x": 440, "y": 140},
    "hindbrain": {"x": 400, "y": 262, "outside": True, "to": (400, 225)},
}

NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def round_path(d: str) -> str:
    d = re.sub(r"\s+", " ", d.strip())
    return NUM.sub(lambda m: f"{float(m.group()):.1f}".rstrip("0").rstrip("."), d)


def region_for(path_ids: list[int], rules: list[dict]) -> str | None:
    """First rule matching the structure (last id of path_ids) or an ancestor.
    An `exact` entry matches only the structure itself. Mirrors
    the check in web/lib/__tests__/brain-regions.test.ts."""
    sid = path_ids[-1]
    for rule in rules:
        for a in rule["allen"]:
            if (sid == a["id"]) if a.get("exact") else (a["id"] in path_ids):
                return rule["region"]
    return None


def region_outlines(paths: list[dict]) -> dict[str, str]:
    """Union of each region's polygons (Bezier curves sampled), as a path."""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import unary_union
    from svgpathtools import parse_path

    polys: dict[str, list] = {}
    for p in paths:
        if not p["region"]:
            continue
        for sub in parse_path(p["d"]).continuous_subpaths():
            pts = []
            for seg in sub:
                for t in (0, 0.25, 0.5, 0.75):
                    z = seg.point(t)
                    pts.append((z.real, z.imag))
            if len(pts) >= 3:
                polys.setdefault(p["region"], []).append(Polygon(pts).buffer(0))
    out = {}
    for region, ps in polys.items():
        # Close the hairline gaps between neighbouring Allen polygons.
        u = unary_union([q.buffer(25) for q in ps]).buffer(-25).simplify(6)
        geoms = list(u.geoms) if isinstance(u, MultiPolygon) else [u]
        segs = []
        for g in geoms:
            if g.area < 20000:
                continue
            for ring in [g.exterior, *g.interiors]:
                if abs(Polygon(ring).area) < 20000:
                    continue
                segs.append("M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in ring.coords) + "Z")
        out[region] = " ".join(segs)
    return out


def main(argv: list[str]) -> int:
    src, structures_json, rules_json, out = argv[1:5]
    report = "--report" in argv
    structures = {
        s["id"]: s for s in json.load(open(structures_json))["msg"]
    }
    rules = json.load(open(rules_json))["rules"]

    tree = ET.parse(src)
    root = tree.getroot()
    width = float(root.get("width"))
    height = float(root.get("height"))
    k = WIDTH / width

    paths = []
    for el in root.iter("{http://www.w3.org/2000/svg}path"):
        sid = int(el.get("structure_id"))
        s = structures.get(sid)
        path_ids = [int(x) for x in s["structure_id_path"].strip("/").split("/")] if s else [sid]
        paths.append(
            {
                "sid": sid,
                "acronym": s["acronym"] if s else "?",
                "path": s["structure_id_path"] if s else f"/{sid}/",
                "region": region_for(path_ids, rules),
                "d": round_path(el.get("d")),
            }
        )

    if report:
        counts: dict[str, int] = {}
        for p in paths:
            counts[p["region"] or "-"] = counts.get(p["region"] or "-", 0) + 1
        print(src, json.dumps(counts, sort_keys=True))
        return 0

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH:g} {height * k:.1f}" '
        'data-region-stroke="fill">',
        "  <!-- Allen Mouse Brain Atlas, P56 sagittal reference atlas, structure",
        "       boundaries (graphic group 28). Image credit: Allen Institute,",
        "       https://alleninstitute.org/citation-policy/ . Downloaded and",
        "       converted by data/regions/makeDoc.txt; contract in",
        "       web/public/regions/README.txt. -->",
        f'  <g transform="scale({k:.6f})">',
    ]
    for p in paths:
        common = (
            f'data-allen-id="{p["sid"]}" data-allen-acronym="{p["acronym"]}" '
            f'data-allen-path="{p["path"]}"'
        )
        if p["region"]:
            lines.append(f'    <path data-region="{p["region"]}" {common} d="{p["d"]}"/>')
        elif p["sid"] == 8 or p["sid"] == 997:
            # whole-brain outline
            lines.append(
                f'    <path {common} fill="#dfe3e8" stroke="#9ca3af" stroke-width="1.2" '
                f'vector-effect="non-scaling-stroke" d="{p["d"]}"/>'
            )
        else:
            lines.append(
                f'    <path {common} fill="#fafafb" stroke="#d9dde3" stroke-width="0.8" '
                f'vector-effect="non-scaling-stroke" d="{p["d"]}"/>'
            )
    # One merged outline per region on top: Allen draws each region as many
    # sub-structures; the page hides their internal lines (stroke = fill, via
    # data-region-stroke="fill" on the root) and these outlines show the
    # coarse regions instead.
    lines.append(
        '    <g fill="none" stroke="#374151" stroke-width="1.6" stroke-linejoin="round" '
        'vector-effect="non-scaling-stroke" pointer-events="none">'
    )
    for region, d in region_outlines(paths).items():
        lines.append(f'      <path data-outline="{region}" vector-effect="non-scaling-stroke" d="{d}"/>')
    lines.append("    </g>")
    lines.append("  </g>")
    lines.append('  <g stroke="#6b7280" stroke-width="1" pointer-events="none">')
    for key, lab in LABELS.items():
        if lab.get("to"):
            x2, y2 = lab["to"]
            y1 = lab["y"] + (4 if lab["y"] < y2 else -14)
            lines.append(f'    <line x1="{lab["x"]}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    lines.append("  </g>")
    names = {
        "cortex": "Cortex",
        "olfactory_bulb": "Olfactory bulb",
        "hippocampus": "Hippocampus",
        "striatum": "Striatum",
        "thalamus": "Thalamus",
        "hypothalamus": "Hypothalamus",
        "midbrain": "Midbrain",
        "cerebellum": "Cerebellum",
        "hindbrain": "Pons / medulla",
    }
    for key, lab in LABELS.items():
        ink = "" if lab.get("outside") else ' data-ink="auto"'
        anchor = f' text-anchor="{lab["anchor"]}"' if lab.get("anchor") else ""
        lines.append(
            f'  <text data-label-for="{key}"{ink}{anchor} x="{lab["x"]}" y="{lab["y"]}">'
            f"{names[key]}</text>"
        )
    lines.append("</svg>")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
