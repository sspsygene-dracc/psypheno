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
};

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
      el.style.fill = p.fill;
      el.style.stroke = "#ffffff";
      el.style.strokeWidth = "2";
      el.style.strokeLinejoin = "round";
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
    for (const el of regions) {
      const key = el.getAttribute("data-region")!;
      const selected = selectedKey === key;
      if (!selected && !outlinedKeys.has(key)) continue;
      const ring = el.cloneNode(false) as SVGGraphicsElement;
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
      // Keep any clip-path an ancestor group applied.
      const clip = el.closest("[clip-path]")?.getAttribute("clip-path");
      if (clip && !ring.getAttribute("clip-path")) ring.setAttribute("clip-path", clip);
      overlay.appendChild(ring);
    }
    const firstLabel = root.querySelector("text[data-label-for]");
    root.insertBefore(overlay, firstLabel ?? null);

    for (const t of Array.from(root.querySelectorAll<SVGTextElement>("text[data-label-for]"))) {
      const key = t.getAttribute("data-label-for")!;
      const p = paint(key);
      if (!t.hasAttribute("data-name")) t.setAttribute("data-name", t.textContent ?? "");
      t.textContent = `${t.getAttribute("data-name")} (${p.count})`;
      if (!t.hasAttribute("text-anchor")) t.setAttribute("text-anchor", "middle");
      t.style.fontSize = "13px";
      t.style.fontWeight = "600";
      t.style.fill = t.getAttribute("data-ink") === "auto" ? p.ink : "#374151";
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
