/**
 * Colour-blind and contrast report for lib/palette.ts.
 *
 *   cd web && npx vite-node scripts/check-palette.ts
 *
 * For every pair of colours that must be told apart, prints CIEDE2000 ΔE under
 * normal vision and simulated protanopia / deuteranopia / tritanopia (Machado
 * et al. 2009), and the WCAG contrast ratio of every text/background pair.
 * Exits 1 if any check fails. The same checks run in `npm test`.
 */
import { VISIONS } from "../lib/colour-vision";
import { runContrastChecks, runPairChecks } from "../lib/palette-checks";

const pad = (s: string, n: number) => (s.length >= n ? s : s + " ".repeat(n - s.length));
const fmt = (n: number) => n.toFixed(1).padStart(6);
const show = (c: unknown) => (Array.isArray(c) ? `rgb(${c.join(",")})` : String(c));

const pairs = runPairChecks();
let failed = 0;
let category = "";
console.log(`${pad("pair", 52)}${VISIONS.map((v) => v.slice(0, 6).padStart(7)).join("")}   min  ok`);
for (const r of pairs) {
  if (r.category !== category) {
    category = r.category;
    console.log(`\n[${category}]`);
  }
  if (!r.ok) failed++;
  console.log(
    `${pad(r.name, 52)}${VISIONS.map((v) => " " + fmt(r.dE[v])).join("")}  ${String(r.min).padStart(4)}  ${r.ok ? "ok" : "FAIL"}` +
      (r.ok ? "" : `   (${show(r.a)} / ${show(r.b)})`),
  );
  if (r.textDE) {
    console.log(`${pad("    label colour", 52)}${VISIONS.map((v) => " " + fmt(r.textDE![v])).join("")}  ${String(10).padStart(4)}`);
  }
}

console.log("\nMinimum ΔE per category (worst simulation):");
const cats = Array.from(new Set(pairs.map((p) => p.category)));
for (const c of cats) {
  const rows = pairs.filter((p) => p.category === c && p.min > 0);
  const worst = rows.reduce((a, b) => (b.worst < a.worst ? b : a));
  const vision = VISIONS.find((v) => worst.dE[v] === worst.worst);
  console.log(`  ${pad(c, 20)} ${worst.worst.toFixed(1).padStart(5)}  (${worst.name}, ${vision})`);
}

console.log("\nWCAG contrast:");
for (const c of runContrastChecks()) {
  if (!c.ok) failed++;
  console.log(`  ${pad(c.name, 44)} ${pad(`${c.fg} on ${c.bg}`, 22)} ${c.ratio.toFixed(2).padStart(6)}:1  (≥${c.min})  ${c.ok ? "ok" : "FAIL"}`);
}

console.log(failed ? `\n${failed} check(s) failed` : "\nAll checks pass");
process.exit(failed ? 1 : 0);
