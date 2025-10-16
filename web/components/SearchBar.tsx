import { SearchSuggestion } from "@/lib/suggestions";
import { useEffect, useRef, useState } from "react";

export default function SearchBar({
  placeholder,
  onSelect,
  value,
  apiPath = "/api/search-text",
  extraBody,
}: {
  placeholder?: string;
  onSelect: (s: SearchSuggestion | null) => void;
  value?: SearchSuggestion | null;
  apiPath?: string;
  extraBody?: Record<string, unknown> | (() => Record<string, unknown>);
}) {
  const [query, setQuery] = useState<string>("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [open, setOpen] = useState<boolean>(false);
  const [highlightIndex, setHighlightIndex] = useState<number>(-1);
  const [suppress, setSuppress] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Sync internal query with external value prop
  useEffect(() => {
    if (value) {
      setSuppress(true);
      setQuery(value.searchQuery);
    } else {
      setQuery("");
    }
  }, [value]);

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
    if (suppress) return;
    const controller = new AbortController();
    const run = async () => {
      const text = query.trim();
      if (!text) {
        setSuggestions([]);
        return;
      }
      try {
        const bodyExtra =
          typeof extraBody === "function" ? extraBody() : extraBody || {};
        const res = await fetch(apiPath, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, ...bodyExtra }),
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
  }, [query, suppress]);

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        if (suggestions.length > 0) {
          setOpen(true);
          setHighlightIndex(0);
        }
        return;
      }
      if (suggestions.length === 0) return;
      setHighlightIndex((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) {
        if (suggestions.length > 0) {
          setOpen(true);
          setHighlightIndex(suggestions.length - 1);
        }
        return;
      }
      if (suggestions.length === 0) return;
      setHighlightIndex(
        (i) => (i - 1 + suggestions.length) % suggestions.length
      );
    } else if (e.key === "Enter") {
      if (!open || suggestions.length === 0) return;
      e.preventDefault();
      const chosen = suggestions[highlightIndex >= 0 ? highlightIndex : 0];
      if (chosen) {
        onSelect(chosen);
        setQuery(chosen.searchQuery);
        setSuppress(true);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const choose = (s: SearchSuggestion) => {
    onSelect(s);
    setQuery(s.searchQuery);
    setSuppress(true);
    setOpen(false);
  };

  return (
    <div ref={containerRef} style={{ width: "100%", position: "relative" }}>
      <input
        value={query}
        onChange={(e) => {
          if (suppress) setSuppress(false);
          setQuery(e.target.value);
          // Clear parent state if input is cleared
          if (e.target.value === "" && value) {
            onSelect(null);
          }
        }}
        onFocus={() => {
          if (query && !suppress) {
            setOpen(true);
          }
        }}
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
          boxSizing: "border-box",
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
              key={`${s.centralGeneId}-${idx}`}
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
                {/* Show human symbol */}
                {s.humanSymbol && (
                  <span style={{ fontWeight: 600 }}>{s.humanSymbol}</span>
                )}
                {/* Show first mouse symbol, if any */}
                {s.mouseSymbols &&
                  s.mouseSymbols.split(",").filter(Boolean)[0] && (
                    <span style={{ opacity: 0.7, fontSize: 12, marginLeft: 8 }}>
                      {s.mouseSymbols.split(",").filter(Boolean)[0]}
                    </span>
                  )}
                {/* Show matching synonym and its species if it triggered the match */}
                {s.searchQuery &&
                  (() => {
                    // Synonyms could be comma separated for both human and mouse
                    const lowerSearch = s.searchQuery.trim().toLowerCase();
                    const findMatchingSynonym = (
                      synonyms: string | null,
                      species: string
                    ) => {
                      if (!synonyms) return null;
                      const found = synonyms
                        .split(",")
                        .map((syn) => syn.trim())
                        .find((syn) => syn.toLowerCase() === lowerSearch);
                      if (found) {
                        return (
                          <span
                            style={{
                              opacity: 0.7,
                              fontSize: 12,
                              marginLeft: 10,
                            }}
                          >
                            {species} synonym:{" "}
                            <span style={{ fontStyle: "italic" }}>{found}</span>
                          </span>
                        );
                      }
                      return null;
                    };
                    // Try human synonyms first, then mouse synonyms
                    return (
                      findMatchingSynonym(s.humanSynonyms, "Human") ||
                      findMatchingSynonym(s.mouseSynonyms, "Mouse")
                    );
                  })()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
