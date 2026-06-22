"""Tests for the deploy SSH/local transport abstraction (issue #203).

The `_Transport` split is what lets `deploy` (SSH from a laptop) and
`wrangler-deploy` (local on psygene) share the same step bodies. These tests
pin the two transports' argv shapes and confirm `_run_psygene` actually runs a
command through the local transport (no SSH, no network).
"""

from __future__ import annotations

import pytest

from processing.deploy import (
    LOCAL_TRANSPORT,
    SSH_TRANSPORT,
    DeployError,
    _run_psygene,
)


def test_ssh_transport_wraps_in_proxy_jump_ssh() -> None:
    argv = SSH_TRANSPORT.argv("echo hi")
    assert argv[0] == "ssh"
    assert "-J" in argv and "hgwdev" in argv
    assert argv[-1] == "echo hi"
    # No TTY unless asked.
    assert "-t" not in argv
    assert "-t" in SSH_TRANSPORT.argv("echo hi", tty=True)


def test_local_transport_runs_bash_no_ssh() -> None:
    argv = LOCAL_TRANSPORT.argv("echo hi")
    assert argv == ["bash", "-c", "echo hi"]
    # tty is irrelevant locally — same argv.
    assert LOCAL_TRANSPORT.argv("echo hi", tty=True) == ["bash", "-c", "echo hi"]


def test_transport_flags() -> None:
    assert SSH_TRANSPORT.is_local is False
    assert SSH_TRANSPORT.interactive_pull is False
    assert LOCAL_TRANSPORT.is_local is True
    # Local pull inherits the TTY so a credential prompt is answerable (§1.1).
    assert LOCAL_TRANSPORT.interactive_pull is True


def test_run_psygene_local_captures_output() -> None:
    result = _run_psygene(
        LOCAL_TRANSPORT, "printf done", desc="echo test", timeout=10
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "done"


def test_run_psygene_local_raises_on_failure() -> None:
    with pytest.raises(DeployError) as exc:
        _run_psygene(
            LOCAL_TRANSPORT, "exit 7", desc="failing step", timeout=10
        )
    assert "failing step" in str(exc.value)


def test_run_psygene_local_check_false_returns_nonzero() -> None:
    result = _run_psygene(
        LOCAL_TRANSPORT, "exit 3", desc="tolerated", timeout=10, check=False
    )
    assert result.returncode == 3
