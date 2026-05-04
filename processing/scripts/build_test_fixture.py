"""Build the bundled top-genes fixture used by `sspsygene load-db --test`.

Pulls top-100 by target Fisher p-value and top-100 by perturbed Cauchy p-value
from a current full-build DB, plus all distinct central_gene_ids from any
perturbed-direction link table with ≤30 distinct gene IDs (i.e. small
perturb-screen perturbation sets — perturb_fish, mouse_perturb, etc.).
The small-link-table sweep guarantees every perturb-screen dataset retains
rows under `--test`, even when its perturbations don't surface in
`gene_combined_pvalues_perturbed` (e.g. perturb_fish_astro reports only
q-values, so it never enters the meta-analysis).

The perturbed combined-p table uses Cauchy because Fisher p-values are null
for rows with only one source p-value, and most perturbation columns have
very few source tables.

Usage:
    processing/.venv-claude/bin/python processing/scripts/build_test_fixture.py
    # or with a custom source DB:
    processing/.venv-claude/bin/python processing/scripts/build_test_fixture.py \\
        --db /path/to/sspsygene.db

Filed alongside sspsygene-dracc/psypheno#130.
"""

import argparse
import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "db" / "sspsygene.db"
FIXTURE_PATH = (
    REPO_ROOT / "processing" / "src" / "processing" / "test_fixture_genes.json"
)

TARGET_LIMIT = 100
PERTURBED_LIMIT = 100
SMALL_LINK_TABLE_THRESHOLD = 30


def fetch_ids(conn: sqlite3.Connection, sql: str, limit: int) -> list[int]:
    return [row[0] for row in conn.execute(sql, (limit,)).fetchall()]


def fetch_small_perturbed_link_genes(conn: sqlite3.Connection) -> set[int]:
    """Genes from perturbed-direction link tables with low cardinality.

    Parses the `link_tables` metadata column on `data_tables`, which stores
    `col:link_table_name:direction` triples comma-joined. For every link
    table tagged `perturbed`, count distinct central_gene_ids; include all
    of them iff the count is at or below SMALL_LINK_TABLE_THRESHOLD.
    """
    rv: set[int] = set()
    rows = conn.execute(
        "SELECT link_tables FROM data_tables WHERE link_tables IS NOT NULL"
    ).fetchall()
    for (raw,) in rows:
        for entry in raw.split(","):
            parts = entry.split(":")
            if len(parts) != 3:
                continue
            _col, link_name, direction = parts
            if direction != "perturbed":
                continue
            try:
                (cnt,) = conn.execute(
                    f'SELECT COUNT(DISTINCT central_gene_id) FROM "{link_name}"'
                ).fetchone()
            except sqlite3.OperationalError:
                continue
            if cnt <= SMALL_LINK_TABLE_THRESHOLD:
                ids = conn.execute(
                    f'SELECT DISTINCT central_gene_id FROM "{link_name}"'
                ).fetchall()
                rv.update(i for (i,) in ids if i is not None)
    return rv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=FIXTURE_PATH)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"error: source DB not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    target_ids = fetch_ids(
        conn,
        """SELECT central_gene_id FROM gene_combined_pvalues_target
           WHERE fisher_pvalue IS NOT NULL
           ORDER BY fisher_pvalue ASC
           LIMIT ?""",
        TARGET_LIMIT,
    )
    perturbed_ids = fetch_ids(
        conn,
        """SELECT central_gene_id FROM gene_combined_pvalues_perturbed
           WHERE cauchy_pvalue IS NOT NULL
           ORDER BY cauchy_pvalue ASC
           LIMIT ?""",
        PERTURBED_LIMIT,
    )
    small_link_ids = fetch_small_perturbed_link_genes(conn)
    conn.close()

    central_gene_ids = sorted(
        set(target_ids) | set(perturbed_ids) | small_link_ids
    )
    payload = {
        "central_gene_ids": central_gene_ids,
        "generated_from": str(args.db.relative_to(REPO_ROOT)),
        "generated_at": _dt.date.today().isoformat(),
        "description": (
            f"top {TARGET_LIMIT} target Fisher + top {PERTURBED_LIMIT} "
            f"perturbed Cauchy + perturbed-side genes from link tables "
            f"with ≤{SMALL_LINK_TABLE_THRESHOLD} distinct gene IDs"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"wrote {len(central_gene_ids)} central_gene_ids "
        f"(target={len(target_ids)}, perturbed={len(perturbed_ids)}, "
        f"small_link={len(small_link_ids)}, "
        f"union={len(central_gene_ids)}) to {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
