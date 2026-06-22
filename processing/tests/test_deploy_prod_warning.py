"""Tests for the prod-rebuild warning prompt (issue #178).

`deploy` should steer operators toward `promote-dev-to-prod` instead of
rebuilding the DB directly on prod. The warning fires only when prod is a
data-rebuild target (`--load-db` / `--preprocess`); a code-only deploy to prod
isn't covered by promote and is left alone.
"""

from __future__ import annotations

import click
import pytest

from processing import deploy
from processing.deploy import _confirm_prod_db_rebuild


def test_warns_and_aborts_on_decline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(click, "confirm", lambda *a, **k: False)
    with pytest.raises(SystemExit):
        _confirm_prod_db_rebuild(["prod"], load_db=True, preprocess=False)


def test_continues_on_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(click, "confirm", lambda *a, **k: True)
    # Should not raise when the operator confirms.
    _confirm_prod_db_rebuild(["prod"], load_db=True, preprocess=False)


def test_fires_for_preprocess_too(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(click, "confirm", lambda *a, **k: calls.append(1) or False)
    with pytest.raises(SystemExit):
        _confirm_prod_db_rebuild(["prod"], load_db=False, preprocess=True)
    assert calls == [1]


def test_no_warning_without_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(click, "confirm", lambda *a, **k: calls.append(1) or False)
    # dev/int with a DB rebuild → no prompt.
    _confirm_prod_db_rebuild(["dev", "int"], load_db=True, preprocess=True)
    assert calls == []


def test_no_warning_for_code_only_prod_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(click, "confirm", lambda *a, **k: calls.append(1) or False)
    # prod --build with no DB rebuild → promote doesn't apply, so no prompt.
    _confirm_prod_db_rebuild(["prod"], load_db=False, preprocess=False)
    assert calls == []


def test_warning_shows_promote_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(click, "confirm", lambda *a, **k: True)
    _confirm_prod_db_rebuild(["prod"], load_db=True, preprocess=False)
    out = capsys.readouterr().out
    assert "sspsygene promote-dev-to-prod" in out
    assert "PRODUCTION" in out


def test_run_deploy_invokes_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_deploy should reach the prod warning after preflight, before anything
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
