"""Tests for the in-place DB-rebuild refusal on int/prod (#178, #225).

`deploy --load-db` used to warn and ask for confirmation before rebuilding the
dataset DB directly on prod. Since #225 it is a hard refusal, and it covers int
as well: the dataset DB is built once on dev and each other instance's DB is
derived from it by `subset-db` at promotion time. Rebuilding in place would
need that site's checkout to hold every dev dataset's gitignored payloads —
what the design exists to prevent — and would bypass the destination check.

A code-only deploy (`--build`, no DB rebuild) still has to happen per site and
is deliberately untouched.
"""

from __future__ import annotations

import pytest

from processing import deploy
from processing.deploy import DeployError, _confirm_prod_db_rebuild


def test_refuses_load_db_on_prod() -> None:
    with pytest.raises(DeployError, match="Refusing to rebuild"):
        _confirm_prod_db_rebuild(["prod"], load_db=True, preprocess=False)


def test_refuses_load_db_on_int() -> None:
    """int is covered now too — it used to build its own tree, which is how an
    embargoed dataset could sit on an instance nobody had declared it for."""
    with pytest.raises(DeployError, match="Refusing to rebuild"):
        _confirm_prod_db_rebuild(["int"], load_db=True, preprocess=False)


def test_refuses_preprocess_too() -> None:
    with pytest.raises(DeployError, match="Refusing to rebuild"):
        _confirm_prod_db_rebuild(["prod"], load_db=False, preprocess=True)


def test_names_every_offending_instance() -> None:
    with pytest.raises(DeployError) as excinfo:
        _confirm_prod_db_rebuild(
            ["dev", "int", "prod"], load_db=True, preprocess=False
        )
    message = str(excinfo.value)
    assert "INTERNAL" in message and "PRODUCTION" in message
    # ...and points at the right promote command for each.
    assert "sspsygene promote-dev-to-int" in message
    assert "sspsygene promote-dev-to-prod" in message
    assert "sspsygene deploy --load-db --instances dev" in message


def test_dev_rebuild_is_allowed() -> None:
    """dev is the build server — this is the supported path, not an error."""
    _confirm_prod_db_rebuild(["dev"], load_db=True, preprocess=True)


def test_code_only_prod_deploy_is_allowed() -> None:
    """`--build` with no DB rebuild isn't covered by promote, so it stays."""
    _confirm_prod_db_rebuild(["prod"], load_db=False, preprocess=False)
    _confirm_prod_db_rebuild(["int", "prod"], load_db=False, preprocess=False)


def test_run_deploy_invokes_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_deploy must reach the guard after preflight and before anything
    # touches the network.
    seen = {}

    def fake_confirm(selected, *, load_db, preprocess):
        seen.update(selected=selected, load_db=load_db, preprocess=preprocess)
        raise SystemExit(0)  # stop before push/SSH

    monkeypatch.setattr(deploy, "_preflight_checks", lambda: None)
    monkeypatch.setattr(deploy, "_confirm_prod_db_rebuild", fake_confirm)
    with pytest.raises(SystemExit):
        deploy.run_deploy(instances="prod", load_db=True)
    assert seen == {"selected": ["prod"], "load_db": True, "preprocess": False}


def test_run_deploy_refuses_before_touching_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the real guard fires, and no git push / SSH happens."""
    calls: list[str] = []
    monkeypatch.setattr(deploy, "_preflight_checks", lambda: None)
    monkeypatch.setattr(deploy, "_step_push", lambda *a, **k: calls.append("push"))
    monkeypatch.setattr(
        deploy, "_run_build_pipeline", lambda *a, **k: calls.append("build")
    )
    with pytest.raises(DeployError, match="Refusing to rebuild"):
        deploy.run_deploy(instances="prod", load_db=True)
    assert calls == []
