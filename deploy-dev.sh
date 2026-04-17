#!/bin/bash
################################################################################
# Deploy to the DEV instance
#
# Run this script directly on hgwdev or psygene.
#
# Usage:
#   ./deploy-dev.sh                       # pull + (rebuild DB if --load-db); no restart
#   ./deploy-dev.sh --load-db             # pull + rebuild database; no restart (no sudo)
#   ./deploy-dev.sh --restart             # also restart the service (needs sudo)
#   ./deploy-dev.sh --load-db --restart   # full deploy with code + data + restart
#
# The default is no restart: the web process auto-detects DB changes (see
# web/lib/db.ts) and picks up a rebuilt SQLite file without a systemctl
# restart. Pass --restart only when the JS code has changed and needs to be
# reloaded.
#
# The dev instance runs on port 3112 at https://psypheno-dev.gi.ucsc.edu and
# is an independent copy of the site (separate checkout and database from
# prod). See docs/server-architecture.md.
################################################################################

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

readonly SITE_PATH="/hive/groups/SSPsyGene/sspsygene_website_dev"
readonly SERVICE_NAME="sspsygene-dev"
readonly CONDA_ENV="sspsygene"

# Environment variables for the dev instance
export SSPSYGENE_CONFIG_JSON="${SITE_PATH}/processing/src/processing/config.json"
export SSPSYGENE_DATA_DIR="${SITE_PATH}/data"
export SSPSYGENE_DATA_DB="${SITE_PATH}/data/db/sspsygene.db"

# ── Color output ─────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log()     { echo -e "${BLUE}[DEV]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Parse arguments ──────────────────────────────────────────────────────────

LOAD_DB=false
RESTART=false
for arg in "$@"; do
    case "$arg" in
        --load-db) LOAD_DB=true ;;
        --restart) RESTART=true ;;
        *) error "Unknown argument: $arg"; echo "Usage: $0 [--load-db] [--restart]"; exit 1 ;;
    esac
done

# ── Deploy ───────────────────────────────────────────────────────────────────

log "Deploying dev instance (${SITE_PATH})"
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

# Step 3: Optionally restart the service (default is no restart)
if [ "$RESTART" = true ]; then
    log "Restarting ${SERVICE_NAME}... (needs sudo)"
    sudo /usr/bin/systemctl restart "$SERVICE_NAME"
else
    log "Skipping service restart (default). The web process auto-detects"
    log "DB changes; pass --restart if JS code changed and needs reloading."
fi

echo
success "Dev deployment complete!"
log "Verify at: https://psypheno-dev.gi.ucsc.edu"
