export function formatAuthors(
  first: string | null | undefined,
  last: string | null | undefined,
  count: number | null | undefined,
): string {
  if (!first && !last) return "";
  if (first && last) {
    if (first === last) return first;
    return count != null && count > 2
      ? `${first}, ..., ${last}`
      : `${first} & ${last}`;
  }
  if (first) return `${first} et al.`;
  return last ?? "";
}
