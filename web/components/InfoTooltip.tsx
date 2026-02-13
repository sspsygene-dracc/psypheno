import { useState, useRef, useEffect } from "react";

export default function InfoTooltip({
  text,
  size = 15,
}: {
  text: string;
  size?: number;
}) {
  const [show, setShow] = useState(false);
  const [position, setPosition] = useState<"below" | "above">("below");
  const iconRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (show && iconRef.current) {
      const rect = iconRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      setPosition(spaceBelow < 80 ? "above" : "below");
    }
  }, [show]);

  return (
    <span
      ref={iconRef}
      style={{ position: "relative", display: "inline-block", marginLeft: 4 }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
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
          style={{
            position: "absolute",
            left: "50%",
            transform: "translateX(-50%)",
            ...(position === "below"
              ? { top: size + 6 }
              : { bottom: size + 6 }),
            background: "#1f2937",
            color: "#ffffff",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 13,
            whiteSpace: "nowrap",
            zIndex: 1000,
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
