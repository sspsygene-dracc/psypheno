import json
import logging
import sys
import shutil
from pathlib import Path

import click

from processing.click.full_help_group import FullHelpGroup
from processing.config import get_sspsygene_config
from processing.run_llm_search import (
    DEFAULT_MAX_BUDGET,
    DEFAULT_MAX_WORKERS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    VALID_MODELS,
    generate_config,
    run_pipeline,
)


@click.group(
    cls=FullHelpGroup,
    context_settings={"max_content_width": shutil.get_terminal_size().columns - 10},
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    default="INFO",
)
@click.option("--log-file", type=str, default=None)
def cli(
    log_level: str,
    log_file: str | None,
) -> None:
    """SSPsyGene Website Data Processing"""
    # Plain-message format keeps the INFO chatter readable; WARNINGs and
    # ERRORs are styled inline by the call site (click.style) so the
    # absence of a level prefix doesn't lose them visually.
    fmt = "%(message)s"
    if log_file:
        logging.basicConfig(filename=log_file, level=log_level, format=fmt)
    else:
        logging.basicConfig(level=log_level, stream=sys.stdout, format=fmt)


@cli.command()
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Load only this dataset directory (e.g. 'mouse-cortex-perturb-4tf'). "
    "If omitted, all datasets are loaded.",
)
@click.option(
    "--skip-missing-datasets",
    is_flag=True,
    default=False,
    help="Skip tables whose input files are missing instead of failing.",
)
@click.option(
    "--no-index",
    is_flag=True,
    default=False,
    help="Skip creating SQLite indexes. Speeds up loading for test purposes.",
)
@click.option(
    "--skip-gene-descriptions",
    is_flag=True,
    default=False,
    help="Skip copying gene descriptions into the database.",
)
@click.option(
    "--skip-meta-analysis",
    is_flag=True,
    default=False,
    help="DEPRECATED no-op. As of issue #176, load-db never computes the "
    "meta-analysis; it is a separate command (`sspsygene meta-analysis`). "
    "Accepted for backwards compatibility with existing scripts.",
)
@click.option(
    "--no-r-cache",
    is_flag=True,
    default=False,
    help="DEPRECATED no-op on load-db (meta-analysis moved to its own "
    "command). Use `sspsygene meta-analysis --no-r-cache`.",
)
@click.option(
    "--export-only",
    is_flag=True,
    default=False,
    help="Skip the DB rebuild and only regenerate the user-facing download "
    "blobs (export_files table) inside the existing out_db. Useful while "
    "iterating on the export step.",
)
@click.option(
    "--test",
    "test_mode",
    is_flag=True,
    default=False,
    help="Restrict each dataset to rows whose gene columns all intersect the "
    "bundled top-genes fixture (processing/src/processing/test_fixture_genes.json), "
    "then cap each unique gene-key combo to 200 rows. Fast end-to-end smoke "
    "tests. Orthogonal to --no-index and --skip-meta-analysis.",
)
def load_db(
    dataset: str | None,
    skip_missing_datasets: bool,
    no_index: bool,
    skip_gene_descriptions: bool,
    skip_meta_analysis: bool,
    no_r_cache: bool,
    export_only: bool,
    test_mode: bool,
) -> None:
    """Load the database"""
    if skip_meta_analysis or no_r_cache:
        click.echo(
            "Note: --skip-meta-analysis / --no-r-cache are no-ops on load-db "
            "as of #176 — meta-analysis is now `sspsygene meta-analysis`.",
            err=True,
        )
    try:
        from processing.sq_load import load_db

        config = get_sspsygene_config(dataset=dataset)
        config.out_db.parent.mkdir(parents=True, exist_ok=True)
        if export_only:
            from processing.exports import write_exports

            if not config.out_db.exists():
                click.echo(
                    f"Error: --export-only requires an existing DB at "
                    f"{config.out_db}; run `sspsygene load-db` first.",
                    err=True,
                )
                sys.exit(1)
            write_exports(config.out_db)
            click.echo(
                click.style(
                    f"Wrote exports as BLOBs into {config.out_db}",
                    fg="green",
                    bold=True,
                )
            )
            return
        test_central_gene_ids: set[int] | None = None
        if test_mode:
            fixture_path = (
                Path(__file__).resolve().parent.parent / "test_fixture_genes.json"
            )
            test_central_gene_ids = set(
                json.loads(fixture_path.read_text())["central_gene_ids"]
            )
            click.echo(
                f"--test: filtering to {len(test_central_gene_ids)} central genes "
                f"from {fixture_path.name}"
            )
        load_db(
            config.out_db,
            config.tables_config.tables,
            assay_types=config.global_config.get("assayTypes", {}),
            condition_types=config.global_config.get("conditionTypes", {}),
            organism_types=config.global_config.get("organismTypes", {}),
            skip_missing=skip_missing_datasets,
            no_index=no_index,
            data_dir=config.base_dir,
            skip_gene_descriptions=skip_gene_descriptions,
            test_central_gene_ids=test_central_gene_ids,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name="meta-analysis")
@click.option(
    "--no-index",
    is_flag=True,
    default=False,
    help="Skip creating SQLite indexes on the per-group combined-pvalue "
    "tables. Speeds up the build for test purposes.",
)
@click.option(
    "--no-r-cache",
    is_flag=True,
    default=False,
    help="Bypass the R meta-analysis result cache (processing/r-cache/). "
    "Forces every R job to re-run; useful when iterating on the R script "
    "before its bytes change.",
)
def meta_analysis(no_index: bool, no_r_cache: bool) -> None:
    """Compute the combined-p-value meta-analysis into sspsygene-meta.db.

    Reads the already-built dataset DB (sspsygene.db) and writes a separate
    meta DB on its own cadence (issue #176). The combination is restricted to
    the assay types listed under `metaAnalysisAssays` in globals.yaml — the
    differential-expression assays whose p-values are comparable (issue #187).
    Run `sspsygene load-db` first if the dataset DB doesn't exist yet."""
    from processing.sq_load import run_meta_analysis

    try:
        config = get_sspsygene_config()
        meta_assays = config.global_config.get("metaAnalysisAssays")
        deg_assays = set(meta_assays) if meta_assays else None
        if deg_assays:
            click.echo(
                f"Meta-analysis assays (from globals.yaml): {sorted(deg_assays)}"
            )
        else:
            click.echo(
                "No metaAnalysisAssays configured — combining ALL p-value "
                "tables (legacy behavior).",
                err=True,
            )
        run_meta_analysis(
            config.out_db,
            config.meta_db,
            hgnc_path=config.gene_map_config.hgnc_file,
            no_index=no_index,
            nimh_csv_path=config.gene_map_config.nimh_gene_list_file,
            tf_list_path=config.gene_map_config.tf_list_file,
            use_r_cache=not no_r_cache,
            deg_assays=deg_assays,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def load_gene_descriptions() -> None:
    """Parse NCBI gene_info.gz into a standalone gene_descriptions.db."""
    from processing.gene_descriptions import build_descriptions_db

    config = get_sspsygene_config()
    build_descriptions_db(config.base_dir)


@cli.command(name="run-llm-search")
@click.argument(
    "yaml_file", type=click.Path(exists=True, dir_okay=False, path_type=str)
)
@click.option(
    "--max-workers",
    type=int,
    default=DEFAULT_MAX_WORKERS,
    show_default=True,
    help="Maximum number of concurrent gene search agents.",
)
@click.option(
    "--model",
    type=str,
    default=DEFAULT_MODEL,
    show_default=True,
    help="Model to use (e.g. sonnet, opus).",
)
@click.option(
    "--max-budget",
    type=str,
    default=DEFAULT_MAX_BUDGET,
    show_default=True,
    help="Maximum budget in USD per agent run.",
)
@click.option(
    "--timeout",
    type=int,
    default=DEFAULT_TIMEOUT,
    show_default=True,
    help="Timeout per gene in seconds.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Resolve jobs and print queue/skip info without running agents.",
)
def run_llm_search(
    yaml_file: str,
    max_workers: int,
    model: str,
    max_budget: str,
    timeout: int,
    dry_run: bool,
) -> None:
    """Run parallel LLM gene searches from a YAML job file."""
    if model not in VALID_MODELS:
        valid_models = ", ".join(VALID_MODELS)
        raise click.ClickException(
            f"Invalid model '{model}'. Valid models: {valid_models}"
        )

    rc = run_pipeline(
        yaml_file=yaml_file,
        model=model,
        max_workers=max_workers,
        max_budget=max_budget,
        timeout=timeout,
        dry_run=dry_run,
    )
    if rc != 0:
        raise click.exceptions.Exit(rc)


@cli.command()
@click.option(
    "--load-db",
    is_flag=True,
    default=False,
    help="Run sspsygene load-db on each deployed site.",
)
@click.option(
    "--no-push",
    is_flag=True,
    default=False,
    help="Skip the local git push step.",
)
@click.option(
    "--instances",
    type=str,
    default=None,
    help="Comma-separated subset of {dev, int, prod} to deploy to. Order in "
    "the list is ignored — instances are iterated in dev→int→prod order. "
    "Note: the three sites are independent (dev stages prod's public datasets; "
    "int is a parallel site for embargoed data) — this is not a staging chain. "
    "Default: all three.",
)
@click.option(
    "--build/--no-build",
    default=False,
    help="Run `npm install` + `npm run build` on each selected site. Default "
    "is off — wranglers running data/preprocess-only deploys never need this. "
    "Pass --build when JS/TS under web/ has changed. Implies --restart unless "
    "--no-restart is passed (the build mints a new Next.js build ID that "
    "invalidates the running service's served HTML).",
)
@click.option(
    "--restart/--no-restart",
    default=None,
    help="Restart web servers on psygene for the deployed instances after "
    "build/load-db (and before --run-tests, so e2e hits the new build). "
    "Default tracks --build: if you're building, you're restarting. Note "
    "the restart step uses kill-and-respawn against npm processes you own, "
    "so it only effectively bounces services whose systemd unit's User= "
    "matches the SSH'd user — currently `jbirgmei`. For other wranglers it "
    "silently no-ops; ask Johannes to restart, or `sudo systemctl restart "
    "sspsygene-dev` if you have sudo and don't mind the prompt.",
)
@click.option(
    "--preprocess",
    is_flag=True,
    default=False,
    help="Run each dataset's preprocess.py on every selected site before "
    "load-db. Independent of --load-db; running preprocess alone refreshes "
    "the processed CSVs without rebuilding the DB.",
)
@click.option(
    "--run-tests",
    is_flag=True,
    default=False,
    help="Run scripts/test.sh all on each selected site after build/load-db "
    "and (if --restart is set) restart, so the e2e tests hit the freshly "
    "deployed code. Includes slow tests (data-correspondence) and playwright "
    "e2e against the deployed URL. Hard-aborts on first failure.",
)
@click.option(
    "--include-meta-analysis",
    is_flag=True,
    default=False,
    help="Also refresh the separate meta DB (sspsygene-meta.db) on each "
    "selected site after load-db (issue #176). Off by default: the dataset "
    "deploy and the meta-analysis are on independent cadences. Equivalent to "
    "running `sspsygene deploy-meta-analysis` on the same instances afterward.",
)
def deploy(
    load_db: bool,
    no_push: bool,
    instances: str | None,
    build: bool,
    restart: bool | None,
    preprocess: bool,
    run_tests: bool,
    include_meta_analysis: bool,
) -> None:
    """Deploy to production, dev, and internal sites on psygene."""
    from processing.deploy import run_deploy

    run_deploy(
        load_db=load_db,
        no_push=no_push,
        instances=instances,
        build=build,
        restart=restart,
        preprocess=preprocess,
        run_tests=run_tests,
        include_meta_analysis=include_meta_analysis,
    )


@cli.command(name="deploy-meta-analysis")
@click.option(
    "--no-push",
    is_flag=True,
    default=False,
    help="Skip the local git push step.",
)
@click.option(
    "--instances",
    type=str,
    default=None,
    help="Comma-separated subset of {dev, int, prod} to refresh meta on. "
    "Default: all three. The three sites are independent — this refreshes "
    "each site's sspsygene-meta.db from that site's own sspsygene.db.",
)
@click.option(
    "--no-r-cache",
    is_flag=True,
    default=False,
    help="Bypass the R meta-analysis result cache on the server, forcing "
    "every R job to re-run.",
)
def deploy_meta_analysis(
    no_push: bool,
    instances: str | None,
    no_r_cache: bool,
) -> None:
    """Refresh sspsygene-meta.db on psygene sites (separate from `deploy`).

    Pushes + pulls code, then runs `sspsygene meta-analysis` on each selected
    site against that site's existing sspsygene.db. Does not rebuild datasets,
    build the web app, or restart services. Invoke on your own cadence when you
    want the combined-p-value rankings refreshed (issue #176)."""
    from processing.deploy import run_deploy_meta_analysis

    run_deploy_meta_analysis(
        no_push=no_push,
        instances=instances,
        no_r_cache=no_r_cache,
    )


@cli.command(name="promote-dev-to-prod")
@click.option(
    "--include-meta-analysis/--no-meta-analysis",
    "include_meta_analysis",
    default=True,
    help="Also copy dev's meta-analysis DB (sspsygene-meta.db) alongside the "
    "main dataset DB. On by default so prod's meta stays consistent with the "
    "promoted main DB. If dev has no meta DB, the meta copy is skipped with a "
    "warning. Pass --no-meta-analysis to copy only the main DB.",
)
@click.option(
    "--local/--ssh",
    "local",
    default=None,
    help="Force running the copy locally (on hgwdev/psygene) or over SSH "
    "(from a laptop, proxy-jumping through hgwdev). Default: auto-detect by "
    "whether the /hive trees are visible as local directories.",
)
@click.option(
    "--min-data-tables",
    type=int,
    default=1,
    show_default=True,
    help="Refuse to promote if dev's main DB has fewer than this many "
    "data_tables rows (guards against promoting a stale/empty build).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be copied without modifying any files.",
)
def promote_dev_to_prod(
    include_meta_analysis: bool,
    local: bool | None,
    min_data_tables: int,
    dry_run: bool,
) -> None:
    """Promote dev's built DB(s) to prod by copying the files (no rebuild).

    Once dev has a verified build, this copies dev's `sspsygene.db` (and, by
    default, `sspsygene-meta.db`) into prod's db dir and atomically swaps them
    in, so prod serves byte-identical bytes instead of re-running preprocess /
    load-db (issue #178). dev and prod share the /hive filesystem, so the copy
    is a local `cp` + `mv` on the server; no cross-host rsync, no service
    restart (the web app re-opens on inode change). int is never a source or
    target.

    Run it from a laptop (SSHes into psygene) or directly on hgwdev/psygene
    (`--local`, or auto-detected):

        # from a laptop
        sspsygene promote-dev-to-prod
        # on hgwdev or psygene
        sspsygene promote-dev-to-prod --local
    """
    from processing.deploy import run_promote_dev_to_prod

    run_promote_dev_to_prod(
        include_meta_analysis=include_meta_analysis,
        local=local,
        dry_run=dry_run,
        min_data_tables=min_data_tables,
    )


@cli.command(name="restart")
@click.argument(
    "instances",
    nargs=-1,
    type=click.Choice(["dev", "int", "prod"], case_sensitive=False),
)
def restart(instances: tuple[str, ...]) -> None:
    """Restart web server(s) on psygene by killing them so systemd respawns.

    Run this DIRECTLY ON psygene. For each named instance it finds the
    `npm start --port NNNN` process, kills it (systemd auto-restarts the
    unit), and waits for the service to come back on localhost. Pass one or
    more of {dev, int, prod}:

        sspsygene restart prod
        sspsygene restart dev int

    This is the standalone equivalent of `sspsygene deploy --restart`'s
    restart step, minus the SSH (it's already local) and minus push/pull/
    build/load-db. Caveat: the systemd units run as jbirgmei, so `kill` only
    bounces a service when you run this as jbirgmei. As another user it finds
    no matching processes and no-ops; ask Johannes, or `sudo systemctl
    restart sspsygene{,-dev,-int}` if you have sudo.
    """
    from processing.deploy import INSTANCE_ORDER, run_restart

    if not instances:
        raise click.UsageError(
            "Specify at least one instance to restart: " + ", ".join(INSTANCE_ORDER)
        )
    requested = {i.lower() for i in instances}
    run_restart([i for i in INSTANCE_ORDER if i in requested])


@cli.command(name="e2e-deployed")
@click.argument(
    "instance", type=click.Choice(["dev", "int", "prod"], case_sensitive=False)
)
def e2e_deployed(instance: str) -> None:
    """Run playwright e2e tests locally against a deployed instance.

    Sets E2E_BASE_URL to the instance's public URL and delegates to
    scripts/test.sh e2e — playwright drives browsers from web/node_modules
    against the deployed site. No ssh, no rebuild, no DB rebuild.
    """
    import os
    import subprocess

    from processing.deploy import INSTANCE_E2E_URLS

    base_url = INSTANCE_E2E_URLS[instance.lower()]
    # main.py is at <repo>/processing/src/processing/click/main.py
    repo_root = Path(__file__).resolve().parents[4]
    test_sh = repo_root / "scripts" / "test.sh"
    if not test_sh.is_file():
        raise click.ClickException(f"scripts/test.sh not found at {test_sh}")

    click.echo(f">>> e2e against {base_url}")
    env = {**os.environ, "E2E_BASE_URL": base_url}
    rc = subprocess.run([str(test_sh), "e2e"], env=env).returncode
    if rc != 0:
        raise click.exceptions.Exit(rc)


@cli.command(name="preprocess")
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Run only this dataset's preprocess.py (e.g. 'satterstrom-2020').",
)
@click.option(
    "--all",
    "run_all",
    is_flag=True,
    default=False,
    help="Run preprocess.py for every dataset that has one, not just those "
    "missing an in_path file.",
)
@click.option(
    "--max-workers",
    type=int,
    default=8,
    show_default=True,
    help="Number of preprocess.py scripts to run in parallel.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List which datasets would be preprocessed without running them.",
)
def preprocess(
    dataset: str | None,
    run_all: bool,
    max_workers: int,
    dry_run: bool,
) -> None:
    """Run dataset preprocess.py scripts locally to regenerate data files.

    The cleaned <table>.tsv/.csv outputs that in_path points at are gitignored
    and produced by preprocess.py from the raw download. After `sspsygene
    sync-data` pulls the raw inputs, this regenerates the cleaned outputs the
    server never persisted. Defaults to only datasets missing an in_path file.
    """
    from processing.preprocess_local import run_local_preprocess

    run_local_preprocess(
        dataset=dataset,
        run_all=run_all,
        dry_run=dry_run,
        max_workers=max_workers,
    )


@cli.command(name="sync-data")
@click.option(
    "--dataset",
    type=str,
    default=None,
    help="Sync only this dataset directory (e.g. 'satterstrom-2020'). "
    "Default: every local dataset directory.",
)
@click.option(
    "--instance",
    type=click.Choice(["dev", "int", "prod"], case_sensitive=False),
    default="dev",
    show_default=True,
    help="Reference instance to pull data files from. dev is effectively a "
    "superset of int and prod, so it's the right default.",
)
@click.option(
    "--host",
    type=str,
    default="hgwdev",
    show_default=True,
    help="SSH host used to read the instance's /hive tree. hgwdev is directly "
    "reachable and sees every instance's tree; pass 'psygene' to proxy-jump.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Also refresh files that already exist locally (rsync by size/mtime). "
    "Default is missing-files-only (never clobbers local edits).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be transferred without writing anything.",
)
def sync_data(
    dataset: str | None,
    instance: str,
    host: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Sync gitignored dataset data files from a reference instance (default: dev).

    Raw downloads and cleaned <table>.tsv outputs aren't in git, so a fresh
    checkout is missing the inputs load-db needs. This rsyncs the missing files
    down from dev without overwriting anything that already exists locally.
    """
    from processing.sync_data import run_sync_data

    run_sync_data(
        dataset=dataset,
        instance=instance.lower(),
        host=host,
        overwrite=overwrite,
        dry_run=dry_run,
    )


@cli.command(name="rsync-dataset")
@click.argument("datasets", nargs=-1, required=True)
@click.option(
    "--instance",
    type=click.Choice(["dev", "int", "prod"], case_sensitive=False),
    default="dev",
    show_default=True,
    help="Server instance to push the data files to.",
)
@click.option(
    "--host",
    type=str,
    default="hgwdev",
    show_default=True,
    help="SSH host used to write the instance's /hive tree. hgwdev is directly "
    "reachable and sees every instance's tree; pass 'psygene' to proxy-jump.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be transferred without writing anything.",
)
def rsync_dataset(
    datasets: tuple[str, ...],
    instance: str,
    host: str,
    dry_run: bool,
) -> None:
    """Push gitignored data files of named DATASETS up to a server instance.

    The push-direction mirror of `sync-data`. Pushes only the gitignored data
    payloads (raw downloads + cleaned <table>.tsv outputs) — never tracked files
    like config.yaml/preprocess.py, which reach the server via `git pull`, so
    the server's git tree stays clean. Creates the remote dataset dir if missing
    and preserves group-write so the next wrangler can overwrite.

    At least one dataset name is required — there is no implicit "all":

        sspsygene rsync-dataset satterstrom-2020 --instance dev
        sspsygene rsync-dataset sfari psychscreen --instance int
    """
    from processing.rsync_dataset import run_rsync_dataset

    run_rsync_dataset(
        datasets=datasets,
        instance=instance.lower(),
        host=host,
        dry_run=dry_run,
    )


@cli.command(name="notify-wranglers")
@click.option(
    "--since",
    type=str,
    default=None,
    help="ISO date (YYYY-MM-DD) to look for changes from. "
    "Defaults to last notification date, or fails if no prior run.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=Path("notify-output"),
    show_default=True,
    help="Directory to write email draft and doc suggestions.",
)
@click.option(
    "--timeout",
    type=int,
    default=300,
    show_default=True,
    help="Timeout in seconds per Claude agent.",
)
def notify_wranglers(since: str | None, output_dir: Path, timeout: int) -> None:
    """Draft a wrangler notification email and doc updates using Claude agents."""
    from processing.notify_wranglers import run_notify

    try:
        run_notify(since=since, output_dir=output_dir, timeout=timeout)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name="generate-llm-config")
@click.option(
    "--top-n",
    type=int,
    default=50,
    show_default=True,
    help="Number of top-ranked genes to include in the generated job file.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Write YAML config to this file path. If omitted, print to stdout.",
)
def generate_llm_config(top_n: int, output: str | None) -> None:
    """Generate an LLM search YAML config from the database."""
    rc = generate_config(top_n=top_n, output=output)
    if rc != 0:
        raise click.exceptions.Exit(rc)
