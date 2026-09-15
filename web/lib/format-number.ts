/**
 * Display formatting for numeric data-table cells.
 *
 * Lives in lib/ rather than inside DataTable so it can be unit-tested.
 */

/** Format a numeric value to avoid floating-point display artifacts. */
export function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (n === 0) return "0";
  // Integers render exactly: no padding to 4 significant digits (8 -> "8.000")
  // and no exponential form (which used to round 12345 down to "1.234e+4" and
  // turn genomic coordinates into "2.188e+7"). Above 2^53 integer-ness is
  // illusory, so those fall through to the exponential branch below.
  if (Number.isInteger(n) && Math.abs(n) <= Number.MAX_SAFE_INTEGER) {
    return String(n);
  }
  const abs = Math.abs(n);
  // Very small or very large: use exponential notation with 4 significant digits
  if (abs < 0.001 || abs >= 1e6) return n.toExponential(3);
  // Otherwise use toPrecision to avoid artifacts like 1.0999999999998
  return n.toPrecision(4);
}

export function formatCellValue(val: unknown): string {
  if (val == null) return "";
  if (typeof val === "number") return formatNumber(val);
  return String(val);
}
