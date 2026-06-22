"""Tests for the `sspsygene deploy` SSH plumbing.

Network-free guards for the two deploy fixes that are easy to regress:

1. `_ssh_command(PSYGENE)` forwards the SSH agent (`-A`). The server checkouts
   pull from GitHub over SSH, so the deploy's `git pull` authenticates *from
   psygene* using the deployer's forwarded laptop agent. Drop `-A` and every
   wrangler without a personal GitHub key on psygene gets
   `Permission denied (publickey)`.
2. The `git pull` step preserves the pull's exit code, so a failed pull fails
   the deploy instead of being swallowed by the chmod backstop's `|| true`.
"""

from __future__ import annotations

import pytest

import subprocess

from processing import deploy
from processing.deploy import (
    PSYGENE,
    DeployError,
    _detect_missing_dependency,
    _run_ssh,
    _ssh_command,
)


def test_ssh_command_psygene_forwards_agent_and_proxy_jumps() -> None:
    argv = _ssh_command(PSYGENE)
    assert argv[0] == "ssh"
    # Agent forwarding so the server-side `git pull` can auth to GitHub.
    assert "-A" in argv
    # Proxy-jump through hgwdev + non-interactive host-key trust.
    assert "-J" in argv and "hgwdev" in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    # The bare psygene hostname is the connection target (last token).
    assert argv[-1] == PSYGENE
    # No TTY unless explicitly requested.
    assert "-t" not in argv
    assert "-t" in _ssh_command(PSYGENE, tty=True)


def test_ssh_command_other_host_is_plain() -> None:
    argv = _ssh_command("hgwdev")
    assert argv == ["ssh", "hgwdev"]
    # Agent forwarding / proxy-jump are psygene-only.
    assert "-A" not in argv
    assert "-J" not in argv


def test_pull_command_preserves_pull_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pull step's shell command must re-exit with the *pull's* status, not
    let the trailing chmod `|| true` mask a failed pull."""
    captured: dict[str, str] = {}

    def fake_run_ssh(host: str, remote_cmd: str, **kwargs: object) -> None:
        captured["host"] = host
        captured["cmd"] = remote_cmd

    monkeypatch.setattr(deploy, "_run_ssh", fake_run_ssh)
    deploy._step_pull_all(["dev"])

    assert captured["host"] == PSYGENE
    cmd = captured["cmd"]
    # The pull runs, its exit code is captured, then re-raised after the chmod.
    assert "git -c safe.directory='*' pull; rc=$?;" in cmd
    assert cmd.rstrip().endswith("exit $rc")
    # The chmod backstop's `|| true` must NOT be the last thing the shell sees
    # (that's the bug — it would mask a failed pull as success).
    assert not cmd.rstrip().endswith("|| true")


def _completed(returncode: int) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(
        args=["ssh"], returncode=returncode, stdout="", stderr="boom"
    )


@pytest.mark.parametrize("stream", [False, True])
def test_run_ssh_raises_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    """A non-zero remote exit must raise (abort the deploy), whether the step
    captures output or streams it — no step fails silently."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(1)
    )
    with pytest.raises(DeployError) as exc:
        _run_ssh(PSYGENE, "false", desc="a failing remote step", stream=stream)
    assert "a failing remote step" in str(exc.value)


def test_run_ssh_check_false_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check=False (used only for the restart step's `ps|grep`, which exits 1
    when no process matches) returns the result instead of raising."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(1))
    result = _run_ssh(PSYGENE, "grep x", desc="find procs", check=False)
    assert result.returncode == 1


@pytest.mark.parametrize(
    "output, expected",
    [
        # pandas' optional-dependency error (the velmeshev_2019 / xlrd case
        # that motivated #204).
        (
            "ImportError: Missing optional dependency 'xlrd'. "
            "Install xlrd >= 2.0.1 for xls Excel support.",
            "xlrd",
        ),
        ("ModuleNotFoundError: No module named 'requests'", "requests"),
        # Dotted submodule names are captured whole.
        (
            "ModuleNotFoundError: No module named 'sklearn.linear_model'",
            "sklearn.linear_model",
        ),
        ("Traceback ...\nImportError: No module named scipy", "scipy"),
        # Not a dependency problem — must not be mistaken for one.
        ("KeyError: 'gene_symbol' column not found", None),
        ("ValueError: Length mismatch", None),
        ("", None),
    ],
)
def test_detect_missing_dependency(output: str, expected: str | None) -> None:
    """A missing-package traceback is turned into the package name so the
    deploy can print an actionable install hint; unrelated errors return
    None so we don't mislabel them as install problems (#204)."""
    assert _detect_missing_dependency(output) == expected
