#!/usr/bin/env bash
# Run playwright e2e tests against a deployed instance.
#
#   scripts/e2e-deployed.sh dev    # https://psypheno-dev.gi.ucsc.edu
#   scripts/e2e-deployed.sh int    # https://psypheno-int.gi.ucsc.edu
#   scripts/e2e-deployed.sh prod   # https://psypheno.gi.ucsc.edu
#
# Runs locally — playwright is in web/node_modules, the browsers it
# drives talk to the deployed URL directly. No ssh, no rebuild, no DB
# rebuild. For a full deploy run sspsygene deploy ... --run-tests.

set -euo pipefail

target="${1:-}"
case "$target" in
  dev)  E2E_BASE_URL="https://psypheno-dev.gi.ucsc.edu" ;;
  int)  E2E_BASE_URL="https://psypheno-int.gi.ucsc.edu" ;;
  prod) E2E_BASE_URL="https://psypheno.gi.ucsc.edu" ;;
  -h|--help|"")
    sed -n '2,11p' "$0"
    exit 0
    ;;
  *)
    echo "unknown instance: $target (expected dev|int|prod)" >&2
    exit 2
    ;;
esac

export E2E_BASE_URL
echo ">>> e2e against $E2E_BASE_URL"
exec "$(dirname "$0")/test.sh" e2e
