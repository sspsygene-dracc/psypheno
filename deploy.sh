#!/bin/bash
################################################################################
# SSPsyGene Deployment Script
#
# Description:
#   Automates deployment to production servers (hgwdev and psygene) after
#   changes have been pushed to the git repository.
#
# Prerequisites:
#   - Changes committed and pushed to origin/main
#   - SSH access configured for hgwdev and psygene
#   - Sudo access on both servers (will prompt for passwords)
#
# Usage:
#   ./deploy.sh
#
# The script will:
#   1. Verify local repository is in clean state
#   2. Deploy to hgwdev: git pull, build, restart service
#   3. Deploy to psygene: git pull, build, restart service
#   4. Report success or failure for each server
#
# Password Prompts:
#   - You will be prompted for sudo password twice (once per server)
#   - Passwords are cached for subsequent commands
#
################################################################################

set -euo pipefail

# Configuration
readonly GITHUB_BRANCH="main"
readonly HGWDEV_HOST="hgwdev"
readonly PSYGENE_HOST="psygene"
readonly HGWDEV_PATH="/hive/groups/SSPsyGene/sspsygene_website"
readonly PSYGENE_PATH="/data/sspsygene_website"
readonly SYSTEMCTL_CMD="sudo /usr/bin/systemctl restart sspsygene-data"

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

################################################################################
# Logging Functions
################################################################################

log() {
    echo -e "${BLUE}[DEPLOY]${NC} $*"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

################################################################################
# Deploy to a Single Server
################################################################################

deploy_to_server() {
    local host="$1"
    local path="$2"

    log "Deploying to $host..."

    # Cache sudo password early (will prompt once)
    log "Caching sudo credentials on $host..."
    if ! ssh "$host" "sudo -v" 2>/dev/null; then
        error "Failed to cache sudo credentials on $host"
        return 1
    fi

    # Run git pull and build in web directory
    log "Pulling latest changes and building on $host..."
    if ! ssh "$host" "cd '$path' && git pull origin $GITHUB_BRANCH && cd web/ && npm run build" 2>&1 | sed "s/^/  [$host] /"; then
        error "Build failed on $host"
        return 1
    fi

    # Restart service (should not prompt due to cached credentials)
    log "Restarting service on $host..."
    if ! ssh "$host" "$SYSTEMCTL_CMD" 2>&1 | sed "s/^/  [$host] /"; then
        error "Service restart failed on $host"
        return 1
    fi

    success "Deployment complete on $host"
    return 0
}

################################################################################
# Pre-flight Checks
################################################################################

check_git_status() {
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        error "Working directory has uncommitted changes"
        error "Please commit or stash your changes before deploying"
        git status --short
        return 1
    fi

    # Check current branch
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD)
    if [ "$current_branch" != "$GITHUB_BRANCH" ]; then
        warn "Current branch is '$current_branch', not '$GITHUB_BRANCH'"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Deployment cancelled"
            return 1
        fi
    fi

    return 0
}

################################################################################
# Main Function
################################################################################

main() {
    log "Starting deployment process..."
    log "Target branch: $GITHUB_BRANCH"
    echo

    # Pre-flight checks
    if ! check_git_status; then
        exit 1
    fi

    echo
    log "Deploying to production servers..."
    echo

    # Deploy to both servers
    local failed=0

    if ! deploy_to_server "$HGWDEV_HOST" "$HGWDEV_PATH"; then
        failed=$((failed + 1))
    fi

    echo

    if ! deploy_to_server "$PSYGENE_HOST" "$PSYGENE_PATH"; then
        failed=$((failed + 1))
    fi

    echo

    # Report final status
    if [ $failed -gt 0 ]; then
        error "Deployment failed on $failed server(s)"
        exit 1
    fi

    success "All deployments completed successfully!"
    log "Servers deployed: $HGWDEV_HOST, $PSYGENE_HOST"
    log ""
    log "Manual verification commands:"
    log "  ssh $HGWDEV_HOST 'systemctl status sspsygene-data'"
    log "  ssh $PSYGENE_HOST 'systemctl status sspsygene-data'"
}

################################################################################
# Script Entry Point
################################################################################

main "$@"
