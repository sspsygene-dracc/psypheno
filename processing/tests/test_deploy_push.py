"""Step 1 of a deploy: push to / check the repository the servers pull from.

The servers `git pull` GIT_BRANCH of DEPLOY_REPO. These tests build throwaway
git repos (two bare "remotes" + a working clone) and check that `_step_push`
pushes when the branch tracks the DEPLOY_REPO remote, never pushes when it
tracks a different one, and refuses when HEAD has commits the servers would
silently not get.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from processing import deploy
from processing.deploy import DeployError


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Isolate from the developer's ~/.gitconfig (signing, hooks, aliases).
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "test@example.com")


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """`work` clone with remotes `deploy` (what the servers pull) and `other`,
    both bare and both starting at the same commit. cwd = work."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _commit(seed, "base")
    for name in ("deploy", "other"):
        _git(tmp_path, "clone", "-q", "--bare", str(seed), f"{name}.git")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", "-o", "deploy", str(tmp_path / "deploy.git"), "work")
    _git(work, "remote", "add", "other", str(tmp_path / "other.git"))
    _git(work, "fetch", "-q", "other")
    monkeypatch.chdir(work)
    # Local paths aren't GitHub URLs; URL matching is covered separately below.
    monkeypatch.setattr(deploy, "_find_deploy_remote", lambda: "deploy")
    return {"work": work, "deploy": tmp_path / "deploy.git", "seed": seed}


def _track(work: Path, remote: str) -> None:
    _git(work, "branch", "-q", "--set-upstream-to", f"{remote}/main", "main")


def _remote_main(bare: Path) -> str:
    return _git(bare, "rev-parse", "main")


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:sspsygene-dracc/psypheno.git",
        "git@github.com:sspsygene-dracc/psypheno",
        "https://github.com/sspsygene-dracc/psypheno.git",
        "https://github.com/sspsygene-dracc/psypheno/",
        "ssh://git@github.com/sspsygene-dracc/psypheno.git",
        "git@github.com:SSPsyGene-DRACC/Psypheno.git",
    ],
)
def test_github_repo_slug_matches_deploy_repo(url: str) -> None:
    assert deploy._github_repo_slug(url) == deploy.DEPLOY_REPO.lower()


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:someone/psypheno.git",
        "git@gitlab.com:sspsygene-dracc/psypheno.git",
        "/hive/groups/SSPsyGene/psypheno.git",
    ],
)
def test_github_repo_slug_rejects_other_repos(url: str) -> None:
    assert deploy._github_repo_slug(url) != deploy.DEPLOY_REPO.lower()


def test_find_deploy_remote_matches_by_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "git@github.com:someone/fork.git")
    _git(repo, "remote", "add", "upstream", "https://github.com/sspsygene-dracc/psypheno")
    monkeypatch.chdir(repo)
    assert deploy._find_deploy_remote() == "upstream"
    _git(repo, "remote", "remove", "upstream")
    assert deploy._find_deploy_remote() is None


def test_branch_tracking_deploy_remote_pushes(repos: dict[str, Path]) -> None:
    head = _commit(repos["work"], "feature")
    result = deploy._step_push()
    assert result.expected_sha == head
    assert result.warning is None
    assert _remote_main(repos["deploy"]) == head


def test_no_push_still_reports_what_the_servers_will_get(
    repos: dict[str, Path],
) -> None:
    before = _remote_main(repos["deploy"])
    _commit(repos["work"], "unpushed")
    result = deploy._step_push(no_push=True)
    assert result.expected_sha == before
    assert _remote_main(repos["deploy"]) == before


def test_other_upstream_in_sync_deploys_without_pushing(
    repos: dict[str, Path],
) -> None:
    _track(repos["work"], "other")
    result = deploy._step_push()
    assert result.expected_sha == _remote_main(repos["deploy"])
    assert result.warning is None


def test_other_upstream_refuses_undeployed_commits(
    repos: dict[str, Path],
) -> None:
    _track(repos["work"], "other")
    before = _remote_main(repos["deploy"])
    _commit(repos["work"], "secret-sauce")
    with pytest.raises(DeployError, match="--allow-undeployed-commits") as exc:
        deploy._step_push()
    assert "add secret-sauce" in exc.value.detail
    # Never pushes on the deploy's behalf.
    assert _remote_main(repos["deploy"]) == before


def test_allow_undeployed_commits_deploys_remote_as_is(
    repos: dict[str, Path],
) -> None:
    _track(repos["work"], "other")
    before = _remote_main(repos["deploy"])
    _commit(repos["work"], "later")
    result = deploy._step_push(allow_undeployed_commits=True)
    assert result.expected_sha == before
    assert result.warning is not None and "add later" in result.warning
    assert _remote_main(repos["deploy"]) == before


def test_other_upstream_behind_deploy_remote_is_fine(
    repos: dict[str, Path], tmp_path: Path
) -> None:
    """Someone else pushed to the deploy remote: the servers get it, and the
    local checkout having nothing extra is not an error."""
    _track(repos["work"], "other")
    pusher = tmp_path / "pusher"
    _git(tmp_path, "clone", "-q", str(repos["deploy"]), "pusher")
    theirs = _commit(pusher, "wrangler-dataset")
    _git(pusher, "push", "-q", "origin", "main")
    result = deploy._step_push()
    assert result.expected_sha == theirs
    assert result.warning is None


def test_no_deploy_remote_falls_back_to_bare_push(
    repos: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deploy, "_find_deploy_remote", lambda: None)
    head = _commit(repos["work"], "x")
    result = deploy._step_push()
    assert result.expected_sha == head
    assert _remote_main(repos["deploy"]) == head


def test_pull_verifies_expected_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_ssh(host: str, remote_cmd: str, **kwargs: object):
        calls.append(remote_cmd)
        rc = 1 if "merge-base --is-ancestor" in remote_cmd else 0
        return subprocess.CompletedProcess(["ssh"], rc, stdout="", stderr="")

    monkeypatch.setattr(deploy, "_run_ssh", fake_run_ssh)
    with pytest.raises(DeployError, match="does not contain abc1234567"):
        deploy._step_pull_all(["dev"], expected_sha="abc1234567deadbeef")
    assert any("merge-base --is-ancestor abc1234567deadbeef HEAD" in c for c in calls)


def test_pull_without_expected_sha_skips_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        deploy,
        "_run_ssh",
        lambda host, cmd, **k: calls.append(cmd)
        or subprocess.CompletedProcess(["ssh"], 0, stdout="", stderr=""),
    )
    deploy._step_pull_all(["dev"])
    assert not any("merge-base" in c for c in calls)


@pytest.mark.parametrize("command", ["deploy", "deploy-meta-analysis", "deploy-overview"])
def test_cli_passes_allow_undeployed_commits(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from click.testing import CliRunner

    from processing.click.main import cli

    target = {
        "deploy": "run_deploy",
        "deploy-meta-analysis": "run_deploy_meta_analysis",
        "deploy-overview": "run_deploy_overview",
    }[command]
    seen: dict[str, object] = {}
    monkeypatch.setattr(deploy, target, lambda **k: seen.update(k))
    result = CliRunner().invoke(
        cli, [command, "--instances", "dev", "--allow-undeployed-commits"]
    )
    assert result.exit_code == 0, result.output
    assert seen["allow_undeployed_commits"] is True
