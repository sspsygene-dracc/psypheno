import { useState, useRef, useLayoutEffect } from "react";

export default function InfoTooltip({
  text,
  size = 15,
}: {
  text: string;
  size?: number;
}) {
  const [show, setShow] = useState(false);
  const [tipStyle, setTipStyle] = useState<{
    top: number;
    left: number;
    visibility: "hidden" | "visible";
  }>({ top: 0, left: 0, visibility: "hidden" });
  const iconRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);

  // Position tooltip in viewport coordinates so it escapes any ancestor
  // overflow:hidden / overflow:auto (e.g. scrollable tables).
  useLayoutEffect(() => {
    if (!show || !iconRef.current || !tooltipRef.current) return;
    const iconRect = iconRef.current.getBoundingClientRect();
    const tipRect = tooltipRef.current.getBoundingClientRect();
    const margin = 8;
    const gap = 6;
    const spaceBelow = window.innerHeight - iconRect.bottom;
    const showAbove = spaceBelow < tipRect.height + gap + margin;
    const top = showAbove
      ? Math.max(margin, iconRect.top - tipRect.height - gap)
      : iconRect.bottom + gap;
    const iconCenter = iconRect.left + iconRect.width / 2;
    let left = iconCenter - tipRect.width / 2;
    if (left < margin) left = margin;
    if (left + tipRect.width > window.innerWidth - margin) {
      left = window.innerWidth - margin - tipRect.width;
    }
    setTipStyle({ top, left, visibility: "visible" });
  }, [show, text]);

  return (
    <span
      ref={iconRef}
      style={{ position: "relative", display: "inline-block", marginLeft: 4 }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => {
        setShow(false);
        setTipStyle((s) => ({ ...s, visibility: "hidden" }));
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: size,
          height: size,
          borderRadius: "50%",
          border: "1px solid #9ca3af",
          color: "#6b7280",
          fontSize: size * 0.65,
          fontWeight: 600,
          cursor: "help",
          lineHeight: 1,
          fontStyle: "italic",
          fontFamily: "Georgia, serif",
          userSelect: "none",
          verticalAlign: "middle",
        }}
      >
        i
      </span>
      {show && (
        <span
          ref={tooltipRef}
          style={{
            position: "fixed",
            top: tipStyle.top,
            left: tipStyle.left,
            visibility: tipStyle.visibility,
            background: "#1f2937",
            color: "#ffffff",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 13,
            whiteSpace: "normal",
            maxWidth: 360,
            width: "max-content",
            lineHeight: 1.4,
            zIndex: 9999,
            pointerEvents: "none",
            boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
            fontWeight: 400,
            fontStyle: "normal",
            fontFamily:
              '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
