import { SearchSuggestion } from "@/state/SearchSuggestion";
import { ALL_CONTROLS_SENTINEL_ID } from "@/lib/gene-query";
import { useEffect, useRef, useState } from "react";

// Module-level LRU keyed by the full request URL. Populated on every
// successful fetch so that backspaces / re-typing a previously-seen prefix
// short-circuit the network entirely. Capped to keep memory bounded.
const SUGGESTION_CACHE_CAP = 100;
const suggestionCache = new Map<string, SearchSuggestion[]>();

function cacheGet(key: string): SearchSuggestion[] | undefined {
  const v = suggestionCache.get(key);
  if (v === undefined) return undefined;
  // Refresh recency by re-inserting.
  suggestionCache.delete(key);
  suggestionCache.set(key, v);
  return v;
}

function cacheSet(key: string, value: SearchSuggestion[]): void {
  if (suggestionCache.has(key)) suggestionCache.delete(key);
  suggestionCache.set(key, value);
  while (suggestionCache.size > SUGGESTION_CACHE_CAP) {
    const oldest = suggestionCache.keys().next().value;
    if (oldest === undefined) break;
    suggestionCache.delete(oldest);
  }
}

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
      setQuery(value.displayLabel ?? value.searchQuery);
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
      const bodyExtra =
        typeof extraBody === "function" ? extraBody() : extraBody || {};
      const params = new URLSearchParams({ text });
      for (const [k, v] of Object.entries(bodyExtra)) {
        if (typeof v === "string") params.set(k, v);
      }
      const url = `${apiPath}?${params.toString()}`;

      const cached = cacheGet(url);
      if (cached !== undefined) {
        setSuggestions(cached);
        setOpen(true);
        return;
      }

      try {
        const res = await fetch(url, {
          method: "GET",
          signal: controller.signal,
        });
        if (!res.ok) return;
        const data = await res.json();
        const next = Array.isArray(data.suggestions) ? data.suggestions : [];
        cacheSet(url, next);
        setSuggestions(next);
        setOpen(true);
      } catch (_) {
        // swallow
      }
    };
    // Slightly longer debounce (was 150 ms): a fast typist would otherwise
    // fire 3–4 in-flight requests per word; 200 ms is still imperceptible
    // to humans but lets each keystroke settle.
    const t = setTimeout(run, 200);
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
        setQuery(chosen.displayLabel ?? chosen.searchQuery);
        setSuppress(true);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const choose = (s: SearchSuggestion) => {
    onSelect(s);
    setQuery(s.displayLabel ?? s.searchQuery);
    setSuppress(true);
    setOpen(false);
  };

  const findMatchingSynonym = (
    searchQuery: string,
    synonyms: string[] | null,
    species: string
  ) => {
    const lowerSearch = searchQuery.trim().toLowerCase();

    if (!synonyms) return null;
    const found = synonyms.find((syn) =>
      syn.toLowerCase().startsWith(lowerSearch)
    );
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

  const getDisplaySynonyms = (
    searchQuery: string,
    humanSynonyms: string[] | null,
    mouseSynonyms: string[] | null
  ) => {
    return (
      findMatchingSynonym(searchQuery, humanSynonyms, "Human") ||
      findMatchingSynonym(searchQuery, mouseSynonyms, "Mouse")
    );
  };

  return (
    <div ref={containerRef} style={{ width: "100%", position: "relative" }}>
      <input
        value={query}
        onChange={(e) => {
          if (suppress) setSuppress(false);
          setQuery(e.target.value);
          // Manual edits (typing, backspace) update the input text and the
          // suggestions dropdown only — the previously selected gene stays
          // selected until the user explicitly clears via the X button or
          // picks a new suggestion. This avoids surprise resets when the
          // user is just refining their query.
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
          border: "1px solid #d1d5db",
          outline: "none",
          fontSize: 16,
          background: "#ffffff",
          color: "#1f2937",
          boxShadow: "0 4px 6px rgba(0,0,0,0.1)",
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
            background: "#ffffff",
            border: "1px solid #d1d5db",
            borderRadius: 12,
            overflow: "hidden",
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
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
                background: idx === highlightIndex ? "#f3f4f6" : "transparent",
                color: "#374151",
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                {/* "control" badge for kind='control' entries (NonTarget1,
                    SafeTarget, GFP, …). Surfaced on autocomplete and on
                    the `control` keyword search. See discussion #19. */}
                {s.kind === "control" && (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: 0.5,
                      textTransform: "uppercase",
                      color: "#7c2d12",
                      background: "#fed7aa",
                      border: "1px solid #fdba74",
                      borderRadius: 4,
                      padding: "1px 6px",
                    }}
                    title="Perturbation control — searchable, but excluded from per-gene aggregates."
                  >
                    control
                  </span>
                )}
                {/* Show human symbol. The synthetic "all controls" entry
                    drops the (human) species suffix and gets a distinct
                    secondary label, since it's not a real gene. */}
                {s.centralGeneId === ALL_CONTROLS_SENTINEL_ID ? (
                  <>
                    <span style={{ fontWeight: 600 }}>CONTROL</span>
                    <span style={{ opacity: 0.7, fontSize: 12, marginLeft: 10 }}>
                      All control genes ({s.datasetCount} entries)
                    </span>
                  </>
                ) : (
                  <>
                    {s.humanSymbol && (
                      <span style={{ fontWeight: 600 }}>
                        {s.humanSymbol} (human)
                      </span>
                    )}
                    {/* Show first mouse symbol, if any */}
                    {s.mouseSymbols && (
                      <span style={{ marginLeft: 8 }}>
                        {s.mouseSymbols.join(", ")} (mouse)
                      </span>
                    )}
                    {/* Show matching synonym and its species if it triggered the match */}
                    {s.searchQuery &&
                      getDisplaySynonyms(
                        s.searchQuery,
                        s.humanSynonyms,
                        s.mouseSynonyms
                      )}
                    <span style={{ opacity: 0.7, fontSize: 12, marginLeft: 10 }}>
                      {s.datasetCount} datasets
                    </span>
                  </>
                )}
              </div>
            </div>
          ))}
          {/* Discoverability hint for the `control` keyword — only shown when
              the user isn't already on it. Lightweight; no extra row when
              they've already typed `control`. */}
          {!/^controls?$/i.test(query.trim()) && (
            <div
              style={{
                padding: "8px 16px",
                fontSize: 12,
                color: "#6b7280",
                borderTop: "1px solid #f3f4f6",
                background: "#fafafa",
              }}
            >
              Tip: type <code>control</code> to list every perturbation
              control across all datasets.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
