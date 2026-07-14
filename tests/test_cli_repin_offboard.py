from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml

import aviato.cli as cli
from aviato.cli import main
from aviato.core.declaration import Declaration
from aviato.core.errors import AviatoError
from aviato.core.model import VariableSpec
from aviato.core.onboarding import resolved_artifacts
from aviato.core.registry import Registry
from aviato.core.scaffold import ScaffoldItem, scaffold
from aviato.github_platform import GitHubPlatform
from aviato.paths import MODULE_SOURCE_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")
_REAL_OPEN_CONSUMER_CONTEXT = cli._open_consumer_context


def _adopt(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
    declaration = tmp_path / ".github/aviato.yaml"
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text(
        "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: '0'\n"
        "variables:\n  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    artifacts = resolved_artifacts(
        Registry(MODULE_SOURCE_ROOT),
        "python-library",
        {"distribution-name": "acme", "import-name": "acme"},
        pin="0",
    )
    items = [
        ScaffoldItem(
            output=artifact.output,
            body=artifact.body,
            comment=artifact.comment,
            seed_once=artifact.seed_once,
            input_hash=artifact.input_hash,
        )
        for artifact in artifacts
    ]
    scaffold(tmp_path, items, profile="python-library", version="0", baseline_existing_seeds=True)


def _git_init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)


def _library_shape(root: Path) -> None:
    (root / "aviato/core").mkdir(parents=True)
    (root / "aviato/core/__init__.py").write_text("", encoding="utf-8")
    (root / "aviato/library/bundles").mkdir(parents=True)
    (root / "aviato/library/scaffold").mkdir(parents=True)
    (root / "aviato/library/policy.yml").write_text("library: {}\n", encoding="utf-8")


@pytest.mark.parametrize(("bootstrap", "skipped"), [(False, False), (True, True)])
def test_repin_target_gate_skip_requires_structure_and_bootstrap_declaration(
    tmp_path: Path, bootstrap: bool, skipped: bool
) -> None:
    _library_shape(tmp_path)
    declaration = Declaration(profile="python-library", version="0", bootstrap=bootstrap)
    args = SimpleNamespace(allow_unresolved_pin=False, override_version_pin=False)

    error = cli._gate_repin_target(tmp_path, "9.0.0", args, declaration)

    assert (error is None) is skipped
    if not skipped:
        assert "version-pin mismatch" in str(error)


def test_legacy_repin_dry_run_remains_readable_but_write_requires_v2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(tmp_path)
    capsys.readouterr()
    # finding 9: the write path now gates on the target resolving as a PUBLISHED ref;
    # fake the resolution here (the refusal paths get their own tests below).

    # _adopt() passed a legacy ``v0``; it must have been canonicalized to bare on write
    # (§6.1 — a leading ``v`` is tolerated on input but never emitted).
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "0"

    # Dry run: reports the move (bare), does not change the declaration. A legacy
    # ``v1.0.0`` target is likewise canonicalized to bare.
    rc = main(["repin", str(tmp_path), "v1.0.0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "re-pin 0 -> 1.0.0" in out
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "0"

    before = (tmp_path / ".github" / "aviato.yaml").read_text(encoding="utf-8")
    rc = main(["repin", str(tmp_path), "v1.0.0", "--write", "--override-version-pin"])
    assert rc == 2
    assert "repin" in capsys.readouterr().err
    assert (tmp_path / ".github" / "aviato.yaml").read_text(encoding="utf-8") == before


def test_repin_rejects_invalid_declared_enum_before_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    declaration_path = tmp_path / ".github" / "aviato.yaml"
    declaration_path.parent.mkdir()
    original = (
        "profile: node-service\nprofile-identity: aviato-profile/node-service/v1\nversion: v0\nvariables:\n"
        "  project-name: sample\n  language-variant: ruby\n"
    )
    declaration_path.write_text(original, encoding="utf-8")

    rc = main(["repin", str(tmp_path), "0", "--write", "--override-version-pin"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert declaration_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("spec", "variables", "invalid_name"),
    [
        (
            VariableSpec("language-variant", "enum", domain=("typescript", "javascript")),
            {"language-variant": "ruby"},
            "language-variant",
        ),
        (VariableSpec("docs-mode", "boolean"), {"docs-mode": "not-a-bool"}, "docs-mode"),
        (VariableSpec("known", "string"), {"known-typo": "value"}, "known-typo"),
        (VariableSpec("token", "string", secret=True), {"token": "secret"}, "token"),
    ],
)
def test_repin_dry_run_rejects_invalid_declaration_before_success(
    spec: VariableSpec,
    variables: dict[str, object],
    invalid_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declaration_path = tmp_path / ".github" / "aviato.yaml"
    declaration_path.parent.mkdir()
    original = yaml.safe_dump(
        {
            "profile": "python-library",
            "profile-identity": "aviato-profile/python-library/v1",
            "version": "0",
            "variables": variables,
        }
    )
    declaration_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_profile", lambda *args, **kwargs: SimpleNamespace(variables=(spec,)))

    rc = main(["repin", str(tmp_path), "1"])

    captured = capsys.readouterr()
    assert rc == 2
    assert invalid_name in captured.err
    assert captured.out == ""  # rejected before any repin plan output
    assert declaration_path.read_text(encoding="utf-8") == original


def test_repin_dry_run_reports_orphaned_overrides_from_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    declaration_path = tmp_path / ".github" / "aviato.yaml"
    declaration_path.parent.mkdir()
    declaration_path.write_text(
        "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: 0\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n"
        "overrides:\n  settings:\n    nonexistent_key: true\n"
        "  pipelines:\n    remove: [ghost-pipeline]\n",
        encoding="utf-8",
    )

    rc = main(["repin", str(tmp_path), "1"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "re-pin 0 -> 1" in captured.out
    assert "nonexistent_key" in captured.out
    assert "ghost-pipeline" in captured.out
    assert "unknown settings override" not in captured.err


def test_legacy_repin_write_rejects_before_touching_hand_edited_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # §5.12: a re-pin must not silently leave hand-edited managed files at the old
    # pin — the no-clobber skip has to be surfaced so the operator knows.
    _adopt(tmp_path)
    ci_path = tmp_path / ".github" / "workflows" / "aviato-ci.yml"
    ci_path.write_text(ci_path.read_text() + "\n# operator hand-edit\n", encoding="utf-8")
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "1.0.0", "--write", "--override-version-pin"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert ci_path.read_text(encoding="utf-8").endswith("# operator hand-edit\n")


def test_repin_write_refuses_unpublished_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # finding 9: a typo'd/unpublished target must fail CLOSED before any file is
    # rewritten — onboard/provision already had this gate; repin (the only sanctioned
    # pin move) did not.
    _adopt(tmp_path)
    capsys.readouterr()

    def unpublished(_pin: str) -> object:
        raise AviatoError("pin does not resolve to a published Library ref")

    monkeypatch.setattr(cli, "_open_published_snapshot", unpublished)

    rc = main(["repin", str(tmp_path), "0.9.9", "--write"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not resolve to a published" in err
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "0"


def test_repin_write_refuses_cross_major_without_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # finding 9 (§2.6): the running tool must refuse to stamp a cross-major target
    # unless explicitly overridden — its templates are not that major's templates.
    _adopt(tmp_path)
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "9.0.0", "--write"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "repin" in err
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "0"


def test_repin_write_unknown_seed_integrity_mutates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(tmp_path)
    (tmp_path / ".github" / "aviato.seed.json").unlink()
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "1.0.0", "--write", "--override-version-pin"])

    captured = capsys.readouterr()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert rc == 2
    assert "repin" in captured.err
    assert after == before


def test_repin_open_pr_unknown_seed_integrity_opens_no_proposal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    clone_path: Path | None = None
    original_declaration = (
        "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: 0\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n"
    )
    proposal_called = False

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        nonlocal clone_path
        if cmd[:3] == ["gh", "repo", "clone"]:
            clone_path = Path(cmd[4])
            (clone_path / ".github").mkdir(parents=True)
            (clone_path / ".github" / "aviato.yaml").write_text(original_declaration, encoding="utf-8")
            _git_init(clone_path)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    rc = main(["repin", "acme/widget", "1.0.0", "--open-pr", "--override-version-pin"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert proposal_called is False
    assert clone_path is not None
    assert (clone_path / ".github" / "aviato.yaml").read_text(encoding="utf-8") == original_declaration


def test_legacy_sync_and_local_repin_require_v2_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir()
    declaration.write_text(
        "profile: python-library\nversion: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    target = tmp_path / "target-library"
    shutil.copytree(MODULE_SOURCE_ROOT, target)
    sentinel = "# target-registry-sentinel\n"
    template = target / "scaffold" / "files" / "ruff.toml.txt"
    template.write_text(template.read_text() + sentinel, encoding="utf-8")
    fetched: list[str] = []

    def fake_consumer_context(_root: Path, loaded_declaration: object) -> object:
        pin = str(loaded_declaration.version)  # type: ignore[attr-defined]
        fetched.append(pin)
        return SimpleNamespace(registry=Registry(MODULE_SOURCE_ROOT), policy_root=MODULE_SOURCE_ROOT)

    def fake_published_snapshot(pin: str) -> object:
        fetched.append(pin)
        return SimpleNamespace(registry=Registry(target), policy_root=target)

    monkeypatch.setattr(cli, "_open_consumer_context", fake_consumer_context)
    monkeypatch.setattr(cli, "_open_published_snapshot", fake_published_snapshot)

    original = declaration.read_text(encoding="utf-8")
    assert main(["sync", str(tmp_path), "--rebaseline-seeds"]) == 2
    assert "repin" in capsys.readouterr().err
    assert declaration.read_text(encoding="utf-8") == original
    assert not (tmp_path / "ruff.toml").exists()


def test_legacy_repin_proposal_requires_v2_before_opening_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _adopt(source)
    target = tmp_path / "target-library"
    shutil.copytree(MODULE_SOURCE_ROOT, target)
    sentinel = "# proposal-target-registry-sentinel\n"
    template = target / "scaffold" / "files" / "ruff.toml.txt"
    template.write_text(template.read_text() + sentinel, encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_snapshot(_pin: str) -> object:
        return SimpleNamespace(registry=Registry(target), policy_root=target)

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            shutil.copytree(source, Path(cmd[4]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(self: GitHubPlatform, *_args: object, **_kwargs: object) -> str:
        captured["ruff"] = (self.workdir / "ruff.toml").read_text()
        return "branch"

    monkeypatch.setattr(cli, "_open_published_snapshot", fake_snapshot)
    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    assert main(["repin", "acme/widget", "0.1.0", "--open-pr"]) == 2
    assert "repin" in capsys.readouterr().err
    assert captured == {}


def test_repin_proposal_rejects_unauthorized_bootstrap_before_target_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    declaration = source / ".github/aviato.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        "profile: python-library\nversion: 0\nbootstrap: true\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    _git_init(source)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            shutil.copytree(source, Path(cmd[4]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "_open_consumer_context", _REAL_OPEN_CONSUMER_CONTEXT)
    for name in (
        "_open_published_snapshot",
        "plan_repin",
        "materialize_items",
        "_dump_consumer_declaration",
        "scaffold",
    ):
        monkeypatch.setattr(cli, name, lambda *_args, _name=name, **_kwargs: pytest.fail(f"crossed {_name}"))
    monkeypatch.setattr(
        GitHubPlatform,
        "open_worktree_proposal",
        lambda *_args, **_kwargs: pytest.fail("opened proposal"),
    )

    rc = main(["repin", "acme/widget", "0.1.0", "--open-pr"])

    assert rc == 2
    assert "structurally verified" in capsys.readouterr().err


def test_repin_proposal_validates_authorized_bootstrap_before_target_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _adopt(source)
    declaration = source / ".github/aviato.yaml"
    declaration.write_text(declaration.read_text(encoding="utf-8") + "bootstrap: true\n", encoding="utf-8")
    (source / "aviato/core").mkdir(parents=True)
    (source / "aviato/core/__init__.py").write_text("", encoding="utf-8")
    shutil.copytree(MODULE_SOURCE_ROOT, source / "aviato/library")
    subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, capture_output=True)
    events: list[str] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            shutil.copytree(source, Path(cmd[4]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def open_current(root: Path, loaded: Declaration) -> object:
        events.append("current")
        return _REAL_OPEN_CONSUMER_CONTEXT(root, loaded)

    def open_target(_pin: str) -> object:
        events.append("target")
        return SimpleNamespace(registry=Registry(MODULE_SOURCE_ROOT), policy_root=MODULE_SOURCE_ROOT)

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "_open_consumer_context", open_current)
    monkeypatch.setattr(cli, "_open_published_snapshot", open_target)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", lambda *_args, **_kwargs: "branch")

    assert main(["repin", "acme/widget", "0.1.0", "--open-pr"]) == 2
    assert "repin" in capsys.readouterr().err
    assert events == ["current", "target"]


def test_repin_open_pr_reports_orphaned_overrides_before_blocking_summary(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            clone = Path(cmd[4])
            (clone / ".github").mkdir(parents=True)
            (clone / ".github" / "aviato.yaml").write_text(
                "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\n"
                "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n"
                "overrides:\n  settings:\n    removed-setting: true\n",
                encoding="utf-8",
            )
            _git_init(clone)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    rc = main(["repin", "acme/widget", "0.1.0", "--open-pr"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "removed-setting" in captured.err
    assert captured.err.index("removed-setting") < captured.err.index("re-pin blocked")


def test_offboard_dry_run_then_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _adopt(tmp_path)
    capsys.readouterr()
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed")

    # Dry run: warns, changes nothing.
    rc = main(["offboard", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry run" in out
    assert (tmp_path / ".github" / "aviato.yaml").exists()

    # Write (strip markers): managed files become plain, declaration removed.
    rc = main(["offboard", str(tmp_path), "--write"])
    assert rc == 0
    assert not (tmp_path / ".github" / "aviato.yaml").exists()
    assert not (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed")


def test_offboard_delete_files_removes_managed(tmp_path: Path) -> None:
    _adopt(tmp_path)
    assert (tmp_path / "ruff.toml").exists()
    rc = main(["offboard", str(tmp_path), "--delete-files", "--write"])
    assert rc == 0
    assert not (tmp_path / "ruff.toml").exists()


def test_offboard_open_pr_opens_reviewable_removal_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    # §5.13: offboarding opens a REVIEWABLE proposal (PR) capturing the removal, with an
    # explicit §2.13 baseline-removal warning — not just a silent local mutation.
    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            dest = Path(cmd[4])
            (dest / ".github").mkdir(parents=True, exist_ok=True)
            (dest / ".github" / "aviato.yaml").write_text(
                "profile: python-library\nversion: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n",
                encoding="utf-8",
            )
            (dest / "ruff.toml").write_text(
                "# aviato:managed profile=python-library version=0 hash=abc\nline-length = 100\n", encoding="utf-8"
            )
            _git_init(dest)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    captured: dict[str, object] = {}

    def fake_proposal(self: GitHubPlatform, repo: str, branch: str, title: str, body: str) -> str:
        captured.update(repo=repo, branch=branch, title=title, body=body)
        # the offboard mutations must have already been applied to the worktree
        captured["declaration_gone"] = not (self.workdir / ".github" / "aviato.yaml").exists()
        captured["marker_stripped"] = not (self.workdir / "ruff.toml").read_text().startswith("# aviato:managed")
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    rc = main(["offboard", "acme-org/widget", "--open-pr"])
    assert rc == 0
    assert captured["repo"] == "acme-org/widget"
    body = cast(str, captured["body"])
    assert "baseline" in body.lower() and "§2.13" in body
    assert captured["declaration_gone"] is True
    assert captured["marker_stripped"] is True
