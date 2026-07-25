import { useEffect, useRef, useState, type ReactNode } from "react";

export default function DoubleScrollX({
  children,
  maxHeight,
}: {
  children: ReactNode;
  /**
   * When set, the content wrapper becomes a bounded-height scroll region
   * (`overflowY: auto`) instead of growing to fit. This is what lets a child
   * table use `position: sticky` for a header row / frozen column: the sticky
   * cells then resolve against this scroll box rather than the page. Omit for
   * the default behavior (unbounded height, page handles vertical scroll).
   */
  maxHeight?: number | string;
}) {
  const topRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const syncingFrom = useRef<"top" | "bottom" | null>(null);
  const [scrollWidth, setScrollWidth] = useState(0);
  const [needsScroll, setNeedsScroll] = useState(false);

  useEffect(() => {
    const wrapper = bottomRef.current;
    if (!wrapper) return;
    const update = () => {
      setScrollWidth(wrapper.scrollWidth);
      setNeedsScroll(wrapper.scrollWidth > wrapper.clientWidth);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(wrapper);
    const inner = wrapper.firstElementChild;
    if (inner) ro.observe(inner);
    const mo = new MutationObserver(update);
    mo.observe(wrapper, { childList: true, subtree: true, characterData: true });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, []);

  const onTopScroll = () => {
    if (syncingFrom.current === "bottom") return;
    if (!topRef.current || !bottomRef.current) return;
    syncingFrom.current = "top";
    bottomRef.current.scrollLeft = topRef.current.scrollLeft;
    requestAnimationFrame(() => {
      syncingFrom.current = null;
    });
  };

  const onBottomScroll = () => {
    if (syncingFrom.current === "top") return;
    if (!topRef.current || !bottomRef.current) return;
    syncingFrom.current = "bottom";
    topRef.current.scrollLeft = bottomRef.current.scrollLeft;
    requestAnimationFrame(() => {
      syncingFrom.current = null;
    });
  };

  return (
    <div>
      <div
        ref={topRef}
        onScroll={onTopScroll}
        style={{
          overflowX: "auto",
          overflowY: "hidden",
          height: needsScroll ? 14 : 0,
        }}
        aria-hidden="true"
      >
        <div style={{ width: scrollWidth, height: 1 }} />
      </div>
      <div
        ref={bottomRef}
        onScroll={onBottomScroll}
        style={
          maxHeight != null
            ? { overflowX: "auto", overflowY: "auto", maxHeight }
            : { overflowX: "auto" }
        }
      >
        {children}
      </div>
    </div>
  );
}
