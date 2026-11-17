import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import type { RegionDrawing } from "@/lib/region-drawings";
import { IN_VITRO_STROKE } from "@/lib/brain-regions";
import { ERROR_TEXT, IN_VITRO, REGION_RING } from "@/lib/palette";

export type RegionPaint = {
  fill: string;
  ink: string;
  /** Text appended to the region's label, e.g. "3" or "3 + 2 in vitro". */
  countText: string;
  /** Accessible description, e.g. "Frontal lobe: 3 tissue datasets". */
  ariaLabel: string;
};

/**
 * Rings drawn over regions:
 *   selected — the region whose panel is open (solid, dark);
 *   cover    — spanned by the hovered / selected coarse bucket (long dashes, amber);
 *   invitro  — has in-vitro datasets (short dashes, violet), so organoids and
 *              iPSC models never read as tissue.
 */
export type RingStyle = "selected" | "cover" | "invitro";
export type Ring = { key: string; style: RingStyle };

const RING_CSS: Record<
  RingStyle,
  { stroke: string; width: string; dash: string | null; halo?: string }
> = {
  // Bright, so it shows on the darkest and the palest fills alike.
  selected: { stroke: REGION_RING.selected, width: "4", dash: null },
  cover: { stroke: REGION_RING.cover, width: "3.5", dash: "9 5" },
  // White halo underneath, so the violet dashes read on the darkest blues too.
  invitro: { stroke: IN_VITRO_STROKE, width: "3", dash: IN_VITRO.dash, halo: "5" },
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
 * paints them, and reports hover / click by key. It knows nothing about the
 * shapes, so any SVG following the contract drops in.
 */
export default function BrainDrawing({
  drawing,
  paint,
  rings,
  selectedKey,
  onHover,
  onSelect,
}: {
  drawing: RegionDrawing;
  paint: (key: string) => RegionPaint;
  rings: readonly Ring[];
  selectedKey: string | null;
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

  // Paint after every render that changes colours, selection or rings.
  useEffect(() => {
    const root = box.current?.querySelector("svg");
    if (!ready || !root) return;
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", `${drawing.title} (schematic)`);
    root.style.width = "100%";
    root.style.height = "auto";
    root.style.display = "block";

    const regions = Array.from(root.querySelectorAll<SVGGraphicsElement>("[data-region]"));
    const strokeFill = root.getAttribute("data-region-stroke") === "fill";
    for (const el of regions) {
      const key = el.getAttribute("data-region")!;
      const p = paint(key);
      el.style.fill = p.fill;
      // data-region-stroke="fill": the file draws a region as many pieces and
      // ships its own merged outlines, so hide the internal piece boundaries.
      el.style.stroke = strokeFill ? p.fill : "#ffffff";
      el.style.strokeWidth = strokeFill ? "0.6" : "1.5";
      el.style.strokeLinejoin = "round";
      // Stroke widths in screen pixels, whatever scale the file's geometry has.
      el.style.setProperty("vector-effect", "non-scaling-stroke");
      el.style.cursor = "pointer";
      el.style.outline = "none";
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", p.ariaLabel);
      el.setAttribute("aria-pressed", String(selectedKey === key));
    }

    // Rings: copies of the region elements drawn on top, so a neighbour
    // painted later never covers them. In-vitro rings first, so the
    // selection / coverage rings sit on top of them.
    root.querySelectorAll(`[${OVERLAY}]`).forEach((n) => n.remove());
    const overlay = document.createElementNS("http://www.w3.org/2000/svg", "g");
    overlay.setAttribute(OVERLAY, "");
    overlay.setAttribute("pointer-events", "none");
    // Insert the overlay first, so ring positions can be measured relative
    // to it (below).
    const firstLabel = root.querySelector("text[data-label-for]");
    root.insertBefore(overlay, firstLabel?.parentNode === root ? firstLabel : null);
    const overlayCtm = (overlay as unknown as SVGGraphicsElement).getCTM?.() ?? null;
    const order: RingStyle[] = ["invitro", "cover", "selected"];
    const sorted = [...rings].sort((a, b) => order.indexOf(a.style) - order.indexOf(b.style));
    for (const { key, style } of sorted) {
      // Ring a region along the file's merged outline (data-outline="<key>")
      // when it ships one, else along each of the region's pieces.
      const outline = root.querySelector<SVGGraphicsElement>(`[data-outline="${CSS.escape(key)}"]`);
      const sources = outline ? [outline] : regions.filter((r) => r.getAttribute("data-region") === key);
      const css = RING_CSS[style];
      for (const el of sources) {
        const ring = el.cloneNode(false) as SVGGraphicsElement;
        ring.removeAttribute("data-outline");
        ring.removeAttribute("data-region");
        ring.removeAttribute("tabindex");
        ring.removeAttribute("role");
        ring.removeAttribute("aria-label");
        ring.removeAttribute("aria-pressed");
        ring.setAttribute("data-ring", style);
        ring.style.cssText = "";
        ring.style.fill = "none";
        ring.style.stroke = css.stroke;
        ring.style.strokeWidth = css.width;
        if (css.dash) ring.style.strokeDasharray = css.dash;
        ring.style.setProperty("vector-effect", "non-scaling-stroke");
        let halo: SVGGraphicsElement | null = null;
        if (css.halo) {
          halo = ring.cloneNode(false) as SVGGraphicsElement;
          halo.setAttribute("data-ring", `${style}-halo`);
          halo.style.stroke = IN_VITRO.halo;
          halo.style.strokeWidth = css.halo;
          halo.style.strokeLinejoin = "round";
        }
        // The overlay sits at the root; carry over any transform the original
        // inherits from its groups (e.g. an atlas drawn at its own scale).
        // Measured against the overlay group, not the <svg>: browsers disagree
        // on whether the outermost <svg>'s CTM includes its viewBox scaling,
        // and using it scaled the ring twice in some (it landed enlarged and
        // off the region). Overlay and original share the same viewport, so
        // that scaling cancels out here in every browser.
        const ctm = el.getCTM?.();
        if (ctm && overlayCtm) {
          const m = overlayCtm.inverse().multiply(ctm);
          ring.setAttribute("transform", `matrix(${m.a} ${m.b} ${m.c} ${m.d} ${m.e} ${m.f})`);
        }
        // Keep any clip-path an ancestor group applied.
        const clip = el.closest("[clip-path]")?.getAttribute("clip-path");
        if (clip && !ring.getAttribute("clip-path")) ring.setAttribute("clip-path", clip);
        if (halo) {
          if (ring.getAttribute("transform")) halo.setAttribute("transform", ring.getAttribute("transform")!);
          if (ring.getAttribute("clip-path")) halo.setAttribute("clip-path", ring.getAttribute("clip-path")!);
          overlay.appendChild(halo);
        }
        overlay.appendChild(ring);
      }
    }

    for (const t of Array.from(root.querySelectorAll<SVGTextElement>("text[data-label-for]"))) {
      const key = t.getAttribute("data-label-for")!;
      const p = paint(key);
      if (!t.hasAttribute("data-name")) t.setAttribute("data-name", t.textContent ?? "");
      t.textContent = `${t.getAttribute("data-name")} (${p.countText})`;
      if (!t.hasAttribute("text-anchor")) t.setAttribute("text-anchor", "middle");
      if (!t.hasAttribute("font-size")) t.style.fontSize = "13px";
      t.style.fontWeight = "600";
      const ink = t.getAttribute("data-ink") === "auto" ? p.ink : "#374151";
      t.style.fill = ink;
      // A halo in the opposite tone keeps labels readable across region
      // boundaries.
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
    return <p style={{ color: ERROR_TEXT, fontSize: 13 }}>Could not load the drawing ({error}).</p>;
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
        // Keyboard focus only: a mouse click also focuses the region, and
        // the card must not pop up away from the pointer then. Place it at
        // the focused region.
        const el = e.target as Element;
        const key = keyAt(el);
        if (!key || !el.matches?.(":focus-visible")) return;
        const r = el.getBoundingClientRect();
        onHover(key, { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 });
      }}
      onBlur={() => onHover(null)}
      // Reserve the drawing's space while the file loads (no layout shift).
      style={{ aspectRatio: `${drawing.viewBox[0]} / ${drawing.viewBox[1]}`, width: "100%" }}
    />
  );
}
