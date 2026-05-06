export type DatasetLink = {
  url: string;
  label?: string;
  description?: string;
};

export function hostFromUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function linkDisplayText(link: DatasetLink): string {
  return link.label ?? hostFromUrl(link.url);
}

// Defang any non-http(s) scheme (notably `javascript:`) before the URL
// reaches an `<a href>`. Source is admin-authored YAML, so this is
// defense-in-depth — but cheap.
function isSafeUrl(raw: string): boolean {
  try {
    const u = new URL(raw);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
}

export function parseDatasetLinks(raw: string | null | undefined): DatasetLink[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: DatasetLink[] = [];
  for (const entry of parsed) {
    if (entry && typeof entry === "object" && "url" in entry) {
      const e = entry as Record<string, unknown>;
      const url = e.url;
      if (typeof url !== "string" || !url) continue;
      if (!isSafeUrl(url)) continue;
      const link: DatasetLink = { url };
      if (typeof e.label === "string") link.label = e.label;
      if (typeof e.description === "string") link.description = e.description;
      out.push(link);
    }
  }
  return out;
}
