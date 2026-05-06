#!/usr/bin/env bash
# Single entry point for SSPsyGene's local test suites. Run before pushing.
#
#   scripts/test.sh             fast suites (pytest unit + tsc + vitest)
#   scripts/test.sh all         everything, including e2e and data-corr
#   scripts/test.sh server      everything except e2e (deploy uses this on
#                               psygene, where playwright browsers aren't
#                               installed)
#   scripts/test.sh python      pytest unit only
#   scripts/test.sh web         tsc + vitest
#   scripts/test.sh e2e         playwright (requires a dev server on :3000,
#                               or set $E2E_BASE_URL)
#   scripts/test.sh data-corr   data-correspondence (requires the built DB)
#
# Fails fast: stops at the first failing suite and prints the one-liner to
# re-run just that suite. There is deliberately no CI — see
# docs/development.md "Testing".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pytest discovery: explicit $PYTEST wins (deploy --run-tests sets this on
# hgwdev where there's no .venv-claude); otherwise prefer the local venv;
# else fall back to whatever's on PATH (e.g. an active conda env).
PYTEST="${PYTEST:-$REPO_ROOT/processing/.venv-claude/bin/pytest}"
if [[ ! -x "$PYTEST" ]]; then
  PYTEST="$(command -v pytest || true)"
fi
if [[ -z "$PYTEST" ]]; then
  echo "no pytest found — set \$PYTEST or install one on PATH" >&2
  exit 2
fi

# Run pytest from the worktree's processing/src so worktrees don't silently
# pick up the main checkout's editable install (CLAUDE.md gotcha #1).
export PYTHONPATH="$REPO_ROOT/processing/src${PYTHONPATH:+:$PYTHONPATH}"

# The pytest conftest needs data/homology/ with the gitignored payload files
# (HGNC_AllianceHomology.rpt, MGI_EntrezGene.rpt, hgnc_complete_set.txt). If
# they're missing here, conftest already prints a clear UsageError telling the
# user to set $SSPSYGENE_TEST_HOMOLOGY_DIR — we don't try to guess the path.

# ---- Suite definitions ------------------------------------------------------

run_python_unit() {
  echo ">>> python unit (pytest, excluding data_correspondence)"
  "$PYTEST" "$REPO_ROOT/processing/tests" \
    --ignore="$REPO_ROOT/processing/tests/data_correspondence" \
    -q
}

run_web_tsc() {
  echo ">>> web tsc --noEmit"
  ( cd "$REPO_ROOT/web" && npx tsc --noEmit )
}

run_web_unit() {
  echo ">>> web vitest (npm run test:run)"
  ( cd "$REPO_ROOT/web" && npm run test:run --silent )
}

run_e2e() {
  echo ">>> web e2e (playwright)"
  # Playwright reads $E2E_BASE_URL (web/playwright.config.ts) — fall back
  # to localhost:3000 only when it isn't set, matching that file's default.
  local probe_url="${E2E_BASE_URL:-http://localhost:3000}"
  if ! curl -sf -o /dev/null --max-time 5 "$probe_url/api/full-datasets"; then
    if [[ -n "${E2E_BASE_URL:-}" ]]; then
      cat >&2 <<EOF
e2e suite couldn't reach \$E2E_BASE_URL=$E2E_BASE_URL.

The deployed site at $probe_url isn't responding to /api/full-datasets.
Check the systemd unit (sspsygene{,-dev,-int}.service) on psygene.
EOF
    else
      cat >&2 <<'EOF'
e2e suite needs a dev server on http://localhost:3000.

Start one in another terminal first:

    cd web && npm run dev

then re-run:  scripts/test.sh e2e

(Refusing to spawn one here so we don't fight whatever you have running.)
EOF
    fi
    return 1
  fi
  ( cd "$REPO_ROOT/web" && npm run test:e2e --silent )
}

run_data_corr() {
  echo ">>> data-correspondence (pytest)"
  # Match the helpers' resolution order: SSPSYGENE_DATA_DB beats
  # SSPSYGENE_DATA_DIR, both beat the repo-local default.
  local db
  if [[ -n "${SSPSYGENE_DATA_DB:-}" ]]; then
    db="$SSPSYGENE_DATA_DB"
  else
    db="${SSPSYGENE_DATA_DIR:-$REPO_ROOT/data}/db/sspsygene.db"
  fi
  if [[ ! -e "$db" ]]; then
    cat >&2 <<EOF
data-correspondence suite needs a built SQLite DB.

Looked for: $db

Build it (or point SSPSYGENE_DATA_DB at an existing one):

    sspsygene load-db

then re-run:  scripts/test.sh data-corr
EOF
    return 1
  fi
  # `-m ""` overrides the project default (`-m 'not slow'` in
  # processing/pyproject.toml) — the data_correspondence suite's two
  # heaviest files (test_meta_analysis_correspondence,
  # test_value_correspondence) are marked `slow` and would otherwise be
  # silently deselected here.
  "$PYTEST" "$REPO_ROOT/processing/tests/data_correspondence" -q -m ""
}

# ---- Dispatch ---------------------------------------------------------------

target="${1:-fast}"

# Map suite name -> the one-liner the user should re-run on failure.
rerun_for() {
  case "$1" in
    python)    echo "scripts/test.sh python" ;;
    web-tsc)   echo "(cd web && npx tsc --noEmit)" ;;
    web-unit)  echo "(cd web && npm run test:run)" ;;
    e2e)       echo "scripts/test.sh e2e" ;;
    data-corr) echo "scripts/test.sh data-corr" ;;
    *)         echo "scripts/test.sh $1" ;;
  esac
}

# Run a single labelled suite; on failure, print the rerun hint and exit.
run_suite() {
  local label="$1" fn="$2"
  if ! "$fn"; then
    echo
    echo "FAIL: $label suite. Re-run with: $(rerun_for "$label")" >&2
    exit 1
  fi
}

case "$target" in
  fast|"")
    run_suite python   run_python_unit
    run_suite web-tsc  run_web_tsc
    run_suite web-unit run_web_unit
    ;;
  all)
    run_suite python    run_python_unit
    run_suite web-tsc   run_web_tsc
    run_suite web-unit  run_web_unit
    run_suite e2e       run_e2e
    run_suite data-corr run_data_corr
    ;;
  server)
    # Everything that doesn't need a browser. Used by `sspsygene deploy
    # --run-tests` on psygene; the e2e suite runs separately from the
    # developer laptop afterwards.
    run_suite python    run_python_unit
    run_suite web-tsc   run_web_tsc
    run_suite web-unit  run_web_unit
    run_suite data-corr run_data_corr
    ;;
  python)
    run_suite python run_python_unit
    ;;
  web)
    run_suite web-tsc  run_web_tsc
    run_suite web-unit run_web_unit
    ;;
  e2e)
    run_suite e2e run_e2e
    ;;
  data-corr)
    run_suite data-corr run_data_corr
    ;;
  -h|--help|help)
    sed -n '2,13p' "$0"
    exit 0
    ;;
  *)
    echo "unknown suite: $target" >&2
    echo "usage: scripts/test.sh [fast|all|server|python|web|e2e|data-corr]" >&2
    exit 2
    ;;
esac

echo
echo "OK: $target suite passed."
