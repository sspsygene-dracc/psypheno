#!/bin/bash
################################################################################
# Deploy to the INTERNAL (int) instance
#
# Run this script directly on hgwdev or psygene.
#
# Usage:
#   ./deploy-int.sh              # pull + build + restart
#   ./deploy-int.sh --load-db    # pull + rebuild database + build + restart
#
# The internal instance is a separate copy of the site used for pre-publication
# data. It runs on port 3111 at https://psypheno-int.gi.ucsc.edu.
#
# See docs/adding-datasets.md for the full workflow.
################################################################################

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

readonly SITE_PATH="/hive/groups/SSPsyGene/sspsygene_website_int"
readonly SERVICE_NAME="sspsygene-int"
readonly CONDA_ENV="sspsygene"

# Environment variables for the internal instance
export SSPSYGENE_CONFIG_JSON="${SITE_PATH}/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="${SITE_PATH}/data"
export SSPSYGENE_DATA_DB="${SITE_PATH}/data/db/sspsygene.db"

# ── Color output ─────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log()     { echo -e "${BLUE}[INT]${NC} $*"; }
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

log "Deploying internal instance (${SITE_PATH})"
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

# Step 3: Build the web application
log "Building web application..."
cd "${SITE_PATH}/web"
npm run build
echo

# Step 4: Restart the service
log "Restarting ${SERVICE_NAME}..."
sudo /usr/bin/systemctl restart "$SERVICE_NAME"

echo
success "Internal deployment complete!"
log "Verify at: https://psypheno-int.gi.ucsc.edu"
