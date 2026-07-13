from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import yaml

import aviato.cli as cli
from aviato.cli import main
from aviato.core.model import VariableSpec
from aviato.core.registry import Registry
from aviato.github_platform import GitHubPlatform
from aviato.paths import MODULE_SOURCE_ROOT


@pytest.fixture(autouse=True)
def _published_target_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def fake_fetch(repository: str, pin: str) -> Iterator[Registry]:  # noqa: ARG001
        yield Registry(MODULE_SOURCE_ROOT)

    monkeypatch.setattr(cli, "fetch_library_registry", fake_fetch)


def _adopt(tmp_path: Path) -> None:
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--pin",
            "v0",
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )
    assert rc == 0


def test_repin_dry_run_then_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(tmp_path)
    capsys.readouterr()
    # finding 9: the write path now gates on the target resolving as a PUBLISHED ref;
    # fake the resolution here (the refusal paths get their own tests below).
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)

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

    # Write: records the new pin (bare) and re-scaffolds the pin-bearing workflows with it.
    # The tool is 0.x and the target is major 1 — §2.6 requires the explicit override.
    rc = main(["repin", str(tmp_path), "v1.0.0", "--write", "--override-version-pin"])
    assert rc == 0
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "1.0.0"
    ci = (tmp_path / ".github" / "workflows" / "aviato-ci.yml").read_text()
    assert "@1.0.0" in ci  # the pin in `uses:` refs moved (bare)
    assert "version=1.0.0" in ci  # marker updated where the body changed (bare)
    assert "v1.0.0" not in ci  # no leading ``v`` is ever emitted (§6.1)
    # §5.12/§2.6: a NON-pin-bearing managed file (body unchanged by the re-pin) must ALSO have
    # its marker restamped to the new pin — not left stale (which would break the §2.6 gate on
    # a later downgrade). This is the H2 regression guard.
    assert "version=1.0.0" in (tmp_path / "ruff.toml").read_text()
    assert "version=0" not in (tmp_path / "ruff.toml").read_text()


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


def test_repin_reports_skipped_hand_edited_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # §5.12: a re-pin must not silently leave hand-edited managed files at the old
    # pin — the no-clobber skip has to be surfaced so the operator knows.
    _adopt(tmp_path)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)
    ci_path = tmp_path / ".github" / "workflows" / "aviato-ci.yml"
    ci_path.write_text(ci_path.read_text() + "\n# operator hand-edit\n", encoding="utf-8")
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "1.0.0", "--write", "--override-version-pin"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "aviato-ci.yml" in out
    assert "skipped" in out.lower()


def test_repin_write_refuses_unpublished_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # finding 9: a typo'd/unpublished target must fail CLOSED before any file is
    # rewritten — onboard/provision already had this gate; repin (the only sanctioned
    # pin move) did not.
    _adopt(tmp_path)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: False)
    capsys.readouterr()

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
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "9.0.0", "--write"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "version-pin mismatch" in err
    assert yaml.safe_load((tmp_path / ".github" / "aviato.yaml").read_text())["version"] == "0"


def test_repin_write_unknown_seed_integrity_mutates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _adopt(tmp_path)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)
    (tmp_path / ".github" / "aviato.seed.json").unlink()
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    capsys.readouterr()

    rc = main(["repin", str(tmp_path), "1.0.0", "--write", "--override-version-pin"])

    captured = capsys.readouterr()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert rc == 2
    assert "--rebaseline-seeds" in captured.err
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
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(*_args: object, **_kwargs: object) -> str:
        nonlocal proposal_called
        proposal_called = True
        return "branch"

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    rc = main(["repin", "acme/widget", "1.0.0", "--open-pr", "--override-version-pin"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "--rebaseline-seeds" in captured.err
    assert proposal_called is False
    assert clone_path is not None
    assert (clone_path / ".github" / "aviato.yaml").read_text(encoding="utf-8") == original_declaration


def test_legacy_sync_then_local_repin_materializes_distinct_target_registry(
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

    @contextmanager
    def fake_fetch(repository: str, pin: str) -> Iterator[Registry]:  # noqa: ARG001
        fetched.append(pin)
        yield Registry(MODULE_SOURCE_ROOT if pin == "0" else target)

    monkeypatch.setattr(cli, "fetch_library_registry", fake_fetch)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)

    assert main(["sync", str(tmp_path), "--rebaseline-seeds"]) == 0
    assert yaml.safe_load(declaration.read_text())["profile-identity"] == "aviato-profile/python-library/v1"
    capsys.readouterr()
    assert main(["repin", str(tmp_path), "0.1.0", "--write"]) == 0
    assert fetched == ["0", "0.1.0"]
    assert sentinel.strip() in (tmp_path / "ruff.toml").read_text()


def test_repin_proposal_materializes_target_registry_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _adopt(source)
    target = tmp_path / "target-library"
    shutil.copytree(MODULE_SOURCE_ROOT, target)
    sentinel = "# proposal-target-registry-sentinel\n"
    template = target / "scaffold" / "files" / "ruff.toml.txt"
    template.write_text(template.read_text() + sentinel, encoding="utf-8")
    captured: dict[str, str] = {}

    @contextmanager
    def fake_fetch(repository: str, pin: str) -> Iterator[Registry]:  # noqa: ARG001
        yield Registry(target)

    def fake_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "repo", "clone"]:
            shutil.copytree(source, Path(cmd[4]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_proposal(self: GitHubPlatform, *_args: object, **_kwargs: object) -> str:
        captured["ruff"] = (self.workdir / "ruff.toml").read_text()
        return "branch"

    monkeypatch.setattr(cli, "fetch_library_registry", fake_fetch)
    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "_published_library_ref_exists", lambda pin: True)
    monkeypatch.setattr(GitHubPlatform, "open_worktree_proposal", fake_proposal)

    assert main(["repin", "acme/widget", "0.1.0", "--open-pr"]) == 0
    assert sentinel.strip() in captured["ruff"]


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
