import { useEffect, type RefObject } from "react";

/**
 * Size a `position: sticky` panel against the space actually left below its
 * *current* top edge, and only let it trap the wheel when it fits there.
 *
 * The obvious `maxHeight: calc(100vh - 2 * top)` is only correct once sticky
 * has engaged. Before the page is scrolled the panel still sits wherever it
 * lands in flow — on /publications that's ~224px down, so the box overhangs the
 * fold by exactly that much. Combined with `overscroll-behavior: contain` the
 * overhang is a wheel trap: the panel's internal scroll ends while its bottom
 * controls are still below the fold, and `contain` then refuses to chain the
 * wheel to the document, so nothing moves at all until the pointer leaves the
 * panel. It reproduces on any viewport shorter than the panel's content plus
 * its flow offset — i.e. routinely when the window is short or the page is
 * zoomed in, which is why it showed up while screen sharing.
 *
 * Shrinking to fit is the fix where there's room to shrink into, but some
 * panels start most of a viewport down the page (the dataset TOC on /download
 * sits below a long intro), and fitting those to the leftover sliver leaves an
 * unusable inch-tall box. So: fit when the result is still usable, otherwise
 * keep a workable height and accept the overhang — and in that case hand the
 * wheel back to the document, so one swipe scrolls the page until the panel
 * pins itself and `contain` becomes correct again.
 *
 * Both values are published as CSS custom properties rather than React state:
 * these panels re-render on scroll already (DatasetToc's scroll-spy), so a
 * state update per frame would be wasteful, and a plain imperative style write
 * would be clobbered by the next render. Callers style themselves with
 * `var(--fit-max-height, <fallback>)` / `var(--fit-overscroll, contain)`, which
 * also gives sensible pre-hydration values.
 */
export function useFitToViewport(
  ref: RefObject<HTMLElement | null>,
  /** Breathing room above and below the panel; match the sticky `top`. */
  gap = 16,
) {
  useEffect(() => {
    let frame = 0;

    const fit = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;

      const viewport = window.innerHeight;
      // Clamp the top at `gap`: once pinned the panel sits there, and a panel
      // scrolled past the top shouldn't get a negative budget.
      const top = Math.max(gap, el.getBoundingClientRect().top);
      const available = viewport - top - gap;
      const floor = Math.min(MIN_USABLE_HEIGHT, viewport - 2 * gap);
      const height = Math.max(available, floor);
      // `contain` is only safe when nothing is hidden below the fold; when the
      // panel overhangs, chaining is what lets the user scroll it into view.
      const fits = height <= available;

      const nextHeight = `${Math.round(height)}px`;
      const nextOverscroll = fits ? "contain" : "auto";
      // Only touch the DOM on change — this runs on every scroll frame.
      if (el.style.getPropertyValue("--fit-max-height") !== nextHeight) {
        el.style.setProperty("--fit-max-height", nextHeight);
      }
      if (el.style.getPropertyValue("--fit-overscroll") !== nextOverscroll) {
        el.style.setProperty("--fit-overscroll", nextOverscroll);
      }
    };

    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(fit);
    };

    fit();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [ref, gap]);
}

/**
 * Below this a panel stops being navigable, so overhanging the fold is the
 * lesser evil — `--fit-overscroll` keeps that case escapable.
 */
const MIN_USABLE_HEIGHT = 280;
