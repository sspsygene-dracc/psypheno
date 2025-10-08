import { useEffect, useRef, useState } from "react";

export type SearchSuggestion = {
  species: string;
  name: string;
  entrezId: string;
};

export default function SearchBar({
  placeholder,
  onSelect,
}: {
  placeholder?: string;
  onSelect: (s: SearchSuggestion) => void;
}) {
  const [query, setQuery] = useState<string>("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [open, setOpen] = useState<boolean>(false);
  const [highlightIndex, setHighlightIndex] = useState<number>(-1);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setHighlightIndex(-1);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      const text = query.trim();
      if (!text) {
        setSuggestions([]);
        return;
      }
      try {
        const res = await fetch("/api/search-text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
          signal: controller.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        setSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
        setOpen(true);
      } catch (_) {
        // swallow
      }
    };
    const t = setTimeout(run, 150);
    return () => {
      controller.abort();
      clearTimeout(t);
    };
  }, [query]);

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex(
        (i) => (i - 1 + suggestions.length) % suggestions.length
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      const chosen = suggestions[highlightIndex >= 0 ? highlightIndex : 0];
      if (chosen) {
        onSelect(chosen);
        setQuery(chosen.name);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const choose = (s: SearchSuggestion) => {
    onSelect(s);
    setQuery(s.name);
    setOpen(false);
  };

  return (
    <div ref={containerRef} style={{ width: "100%", position: "relative" }}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => query && setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder || "Search for a gene"}
        style={{
          width: "100%",
          padding: "16px 18px",
          borderRadius: 12,
          border: "1px solid #334155",
          outline: "none",
          fontSize: 16,
          background: "#111827",
          color: "#e5e7eb",
          boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
        }}
      />
      {open && suggestions.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            marginTop: 8,
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 12,
            overflow: "hidden",
            boxShadow: "0 14px 40px rgba(0,0,0,0.35)",
            zIndex: 20,
          }}
        >
          {suggestions.map((s, idx) => (
            <div
              key={`${s.entrezId}-${idx}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(s)}
              onMouseEnter={() => setHighlightIndex(idx)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 16px",
                cursor: "pointer",
                background: idx === highlightIndex ? "#1e293b" : "transparent",
                color: "#e2e8f0",
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <span style={{ opacity: 0.7, fontSize: 12 }}>{s.species}</span>
              </div>
              <span style={{ opacity: 0.7, fontSize: 12 }}>
                Entrez {s.entrezId}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
