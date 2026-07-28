"""Site-instance identity: the canonical instance names and their /hive paths.

Split out of deploy.py (#225) so that config.py — imported by essentially
everything — can validate a dataset's `deployTo:` against the real instance
list without pulling in click and the whole deploy stack. It also collapses the
copy of INSTANCE_PATHS that pull_data.py used to keep of its own.

Deliberately dependency-free: constants only, no imports, no side effects.
"""

from __future__ import annotations

PROD_PATH = "/hive/groups/SSPsyGene/sspsygene_website"
DEV_PATH = "/hive/groups/SSPsyGene/sspsygene_website_dev"
INT_PATH = "/hive/groups/SSPsyGene/sspsygene_website_int"

# Display/iteration order when --instances picks multiple, and the canonical
# token list a dataset's `deployTo:` is validated against. The three sites are
# independent deploys — dev is the build superset, prod and int are each
# subsetted from it — so this ordering is for log readability and stable
# normalization, not a gating chain.
INSTANCE_ORDER = ("dev", "int", "prod")
INSTANCE_PATHS = {"dev": DEV_PATH, "int": INT_PATH, "prod": PROD_PATH}
INSTANCE_LABELS = {"dev": "Dev", "int": "Internal", "prod": "Production"}
INSTANCE_E2E_URLS = {
    "dev": "https://psypheno-dev.gi.ucsc.edu",
    "int": "https://psypheno-int.gi.ucsc.edu",
    "prod": "https://psypheno.gi.ucsc.edu",
}
# Ports each instance's `npm start` listens on (Apache reverse-proxies the
# public URL to localhost:PORT). Used by _step_restart_psygene to target only
# the deployed instance(s) rather than killing every Next.js process.
INSTANCE_PORTS = {"dev": 3112, "int": 3111, "prod": 3110}

# `dev` is mandatory in every dataset's `deployTo` (#225): it is the superset
# that every other destination is derived from.
REQUIRED_DESTINATION = "dev"
