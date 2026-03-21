#!/bin/bash
################################################################################
# Deploy to the PRODUCTION instance
#
# Run this script directly on hgwdev or psygene.
#
# Usage:
#   ./deploy-prod.sh              # pull + restart
#   ./deploy-prod.sh --load-db    # pull + rebuild database + restart
#
# The production instance runs on port 3110 at https://psypheno.gi.ucsc.edu.
# The dev instance (port 3112, psypheno-dev.gi.ucsc.edu) shares the same code
# and data, so this script restarts both services.
#
# See docs/adding-datasets.md for the full workflow.
################################################################################

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

readonly SITE_PATH="/hive/groups/SSPsyGene/sspsygene_website"
readonly CONDA_ENV="sspsygene"

# Environment variables for the production instance
export SSPSYGENE_CONFIG_JSON="${SITE_PATH}/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="${SITE_PATH}/data"
export SSPSYGENE_DATA_DB="${SITE_PATH}/data/db/sspsygene.db"

# ── Color output ─────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log()     { echo -e "${BLUE}[PROD]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Parse arguments ──────────────────────────────────────────────────────────

LOAD_DB=false
for arg in "$@"; do
    case "$arg" in
        --load-db) LOAD_DB=true ;;
        *) error "Unknown argument: $arg"; echo "Usage: $0 [--load-db]"; exit 1 ;;
    esac
done

# ── Deploy ───────────────────────────────────────────────────────────────────

log "Deploying production instance (${SITE_PATH})"
echo

# Step 1: Pull latest code
log "Pulling latest code..."
cd "$SITE_PATH"
git pull
echo

# Step 2: Optionally rebuild the database
if [ "$LOAD_DB" = true ]; then
    log "Loading database (this may take a while)..."
    source "$HOME/opt_rocky9/miniconda3/etc/profile.d/conda.sh"
    conda run --no-capture-output -n "$CONDA_ENV" sspsygene load-db
    echo
fi

# Step 3: Restart both prod and dev services (they share the same code/data)
log "Restarting sspsygene (prod) and sspsygene-dev (dev)... (needs sudo)"
sudo /usr/bin/systemctl restart sspsygene
sudo /usr/bin/systemctl restart sspsygene-dev

echo
success "Production deployment complete!"
log "Verify at: https://psypheno.gi.ucsc.edu"
log "Dev mirror: https://psypheno-dev.gi.ucsc.edu"
