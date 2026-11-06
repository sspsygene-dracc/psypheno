import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import type { RegionDrawing } from "@/lib/region-drawings";

export type RegionPaint = {
  fill: string;
  ink: string;
  /** Specific dataset count, appended to the label. */
  count: number;
  label: string;
  /** Draw the fill hatched (gene view: the gene was only measured here). */
  hatch?: boolean;
};

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * A diagonal-hatch pattern in `color`, sized for `el`'s coordinate system
 * (atlas files draw at their own scale inside a transformed group, and a
 * pattern is laid out in the user space of the element that uses it).
 */
function ensureHatch(root: SVGSVGElement, el: SVGGraphicsElement, color: string): string {
  const rootA = root.getCTM()?.a ?? 1;
  const elA = el.getCTM()?.a ?? 1;
  const ratio = elA ? rootA / elA : 1;
  const id = `rg-hatch-${color.replace(/[^0-9a-f]/gi, "")}-${Math.round(ratio * 100)}`;
  if (root.querySelector(`#${id}`)) return id;
  let defs = root.querySelector("defs[data-region-defs]");
  if (!defs) {
    defs = document.createElementNS(SVG_NS, "defs");
    defs.setAttribute("data-region-defs", "");
    root.insertBefore(defs, root.firstChild);
  }
  const size = 7 * ratio;
  const pattern = document.createElementNS(SVG_NS, "pattern");
  pattern.setAttribute("id", id);
  pattern.setAttribute("patternUnits", "userSpaceOnUse");
  pattern.setAttribute("width", String(size));
  pattern.setAttribute("height", String(size));
  pattern.setAttribute("patternTransform", "rotate(45)");
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("width", String(size));
  rect.setAttribute("height", String(size));
  rect.setAttribute("fill", color);
  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("x1", "0");
  line.setAttribute("y1", "0");
  line.setAttribute("x2", "0");
  line.setAttribute("y2", String(size));
  line.setAttribute("stroke", "#ffffff");
  line.setAttribute("stroke-width", String(size * 0.4));
  pattern.append(rect, line);
  defs.appendChild(pattern);
  return id;
}

// Drawings are static assets; fetch each once per page load.
const svgCache = new Map<string, Promise<string>>();
function loadSvg(src: string): Promise<string> {
  let p = svgCache.get(src);
  if (!p) {
    p = fetch(src).then((r) => {
      if (!r.ok) throw new Error(`${src}: ${r.status}`);
      return r.text();
    });
    p.catch(() => svgCache.delete(src));
    svgCache.set(src, p);
  }
  return p;
}

const OVERLAY = "data-region-overlay";

/**
 * One drawing with clickable regions. The geometry is a vendored SVG whose
 * clickable elements carry data-region="<key>" (contract in
 * web/public/regions/README.txt); this component only finds those elements,
 * paints them, and reports hover / click by key — it knows nothing about the
 * shapes, so any SVG following the contract drops in.
 */
export default function BrainDrawing({
  drawing,
  paint,
  selectedKey,
  outlinedKeys,
  onHover,
  onSelect,
}: {
  drawing: RegionDrawing;
  paint: (key: string) => RegionPaint;
  selectedKey: string | null;
  /** Regions an in-vitro tray group is hovered for (dotted outline). */
  outlinedKeys: ReadonlySet<string>;
  onHover: (key: string | null, pos?: { clientX: number; clientY: number }) => void;
  onSelect: (key: string) => void;
}) {
  const [svg, setSvg] = useState<{ src: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    loadSvg(drawing.src)
      .then((text) => !cancelled && setSvg({ src: drawing.src, text }))
      .catch((e) => !cancelled && setError(String(e?.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [drawing.src]);

  const ready = svg?.src === drawing.src;
  const svgText = ready ? svg.text : null;

  // Inline the SVG imperatively, once per file: React leaves a childless
  // div's content alone, so hover re-renders never replace the elements
  // (dangerouslySetInnerHTML re-set it, which swallowed clicks mid-gesture).
  // Vendored, same-origin static SVG (web/public/regions); no user input.
  useLayoutEffect(() => {
    if (box.current) box.current.innerHTML = svgText ?? "";
  }, [svgText]);

  // Paint after every render that changes colours, selection or outlines.
  useEffect(() => {
    const root = box.current?.querySelector("svg");
    if (!ready || !root) return;
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", `${drawing.title} (schematic)`);
    root.style.width = "100%";
    root.style.height = "auto";
    root.style.display = "block";

    const regions = Array.from(root.querySelectorAll<SVGGraphicsElement>("[data-region]"));
    for (const el of regions) {
      const key = el.getAttribute("data-region")!;
      const p = paint(key);
      el.style.fill = p.hatch ? `url(#${ensureHatch(root, el, p.fill)})` : p.fill;
      // data-region-stroke="fill": the file draws a region as many pieces and
      // ships its own merged outlines, so hide the internal piece boundaries.
      const strokeFill = root.getAttribute("data-region-stroke") === "fill";
      el.style.stroke = strokeFill ? p.fill : "#ffffff";
      el.style.strokeWidth = strokeFill ? "0.6" : "1.5";
      el.style.strokeLinejoin = "round";
      // Stroke widths in screen pixels, whatever scale the file's geometry has.
      el.style.setProperty("vector-effect", "non-scaling-stroke");
      el.style.cursor = "pointer";
      el.style.outline = "none";
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", `${p.label}: ${p.count} dataset${p.count === 1 ? "" : "s"}`);
      el.setAttribute("aria-pressed", String(selectedKey === key));
    }

    // Selection / intended-identity rings: copies of the region elements
    // drawn on top, so a neighbour painted later never covers them.
    root.querySelectorAll(`[${OVERLAY}]`).forEach((n) => n.remove());
    const overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
    overlay.setAttribute(OVERLAY, "");
    overlay.setAttribute("pointer-events", "none");
    const ringKeys = new Set(outlinedKeys);
    if (selectedKey) ringKeys.add(selectedKey);
    // Ring a region along the file's merged outline (data-outline="<key>")
    // when it ships one, else along each of the region's pieces.
    const ringSources = Array.from(ringKeys).flatMap((key) => {
      const outline = root.querySelector<SVGGraphicsElement>(`[data-outline="${CSS.escape(key)}"]`);
      return outline
        ? [{ key, el: outline }]
        : regions.filter((r) => r.getAttribute("data-region") === key).map((el) => ({ key, el }));
    });
    for (const { key, el } of ringSources) {
      const selected = selectedKey === key;
      const ring = el.cloneNode(false) as SVGGraphicsElement;
      ring.removeAttribute("data-outline");
      ring.removeAttribute("data-region");
      ring.removeAttribute("tabindex");
      ring.removeAttribute("role");
      ring.removeAttribute("aria-label");
      ring.removeAttribute("aria-pressed");
      ring.style.cssText = "";
      ring.style.fill = "none";
      ring.style.stroke = selected ? "#111827" : "#7c3aed";
      ring.style.strokeWidth = selected ? "3" : "2.5";
      if (!selected) ring.style.strokeDasharray = "5 4";
      ring.style.setProperty("vector-effect", "non-scaling-stroke");
      // The overlay sits at the root; carry over any transform the original
      // inherits from its groups (e.g. an atlas drawn at its own scale).
      const ctm = (el as SVGGraphicsElement).getCTM?.();
      const rootCtm = root.getCTM?.();
      if (ctm && rootCtm) {
        const m = rootCtm.inverse().multiply(ctm);
        ring.setAttribute("transform", `matrix(${m.a} ${m.b} ${m.c} ${m.d} ${m.e} ${m.f})`);
      }
      // Keep any clip-path an ancestor group applied.
      const clip = el.closest("[clip-path]")?.getAttribute("clip-path");
      if (clip && !ring.getAttribute("clip-path")) ring.setAttribute("clip-path", clip);
      overlay.appendChild(ring);
    }
    const firstLabel = root.querySelector("text[data-label-for]");
    root.insertBefore(overlay, firstLabel?.parentNode === root ? firstLabel : null);

    for (const t of Array.from(root.querySelectorAll<SVGTextElement>("text[data-label-for]"))) {
      const key = t.getAttribute("data-label-for")!;
      const p = paint(key);
      if (!t.hasAttribute("data-name")) t.setAttribute("data-name", t.textContent ?? "");
      t.textContent = `${t.getAttribute("data-name")} (${p.count})`;
      if (!t.hasAttribute("text-anchor")) t.setAttribute("text-anchor", "middle");
      if (!t.hasAttribute("font-size")) t.style.fontSize = "13px";
      t.style.fontWeight = "600";
      const ink = t.getAttribute("data-ink") === "auto" ? p.ink : "#374151";
      t.style.fill = ink;
      // A halo in the opposite tone keeps labels readable on hatched fills
      // and across region boundaries.
      t.style.stroke = ink === "#ffffff" ? "rgba(17,24,39,0.45)" : "rgba(255,255,255,0.85)";
      t.style.strokeWidth = "3px";
      t.style.strokeLinejoin = "round";
      t.style.setProperty("paint-order", "stroke");
      t.style.pointerEvents = "none";
      t.style.userSelect = "none";
    }
  });

  const keyAt = (target: EventTarget | null): string | null => {
    const el = (target as Element | null)?.closest?.("[data-region]");
    return el ? el.getAttribute("data-region") : null;
  };

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const key = keyAt(e.target);
    onHover(key, key ? { clientX: e.clientX, clientY: e.clientY } : undefined);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const key = keyAt(e.target);
    if (key && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      onSelect(key);
    }
  };

  if (error) {
    return <p style={{ color: "#b91c1c", fontSize: 13 }}>Could not load the drawing ({error}).</p>;
  }
  return (
    <div
      ref={box}
      onMouseMove={onMove}
      onMouseLeave={() => onHover(null)}
      onClick={(e) => {
        const key = keyAt(e.target);
        if (key) onSelect(key);
      }}
      onKeyDown={onKey}
      onFocus={(e) => {
        const key = keyAt(e.target);
        if (key) onHover(key);
      }}
      onBlur={() => onHover(null)}
      style={{ minHeight: ready ? undefined : 240 }}
    />
  );
}
