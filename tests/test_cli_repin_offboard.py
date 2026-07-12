from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import aviato.cli as cli
from aviato.cli import main


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


def test_repin_rejects_invalid_declared_enum_before_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    declaration_path = tmp_path / ".github" / "aviato.yaml"
    declaration_path.parent.mkdir()
    original = (
        "profile: node-service\nversion: v0\nvariables:\n"
        "  project-name: sample\n  language-variant: ruby\n"
    )
    declaration_path.write_text(original, encoding="utf-8")

    rc = main(["repin", str(tmp_path), "0", "--write", "--override-version-pin"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert declaration_path.read_text(encoding="utf-8") == original


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
    def fake_run(cmd, **__):
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

    captured: dict = {}

    def fake_proposal(self, repo, branch, title, body):  # noqa: ANN001
        captured.update(repo=repo, branch=branch, title=title, body=body)
        # the offboard mutations must have already been applied to the worktree
        captured["declaration_gone"] = not (self.workdir / ".github" / "aviato.yaml").exists()
        captured["marker_stripped"] = not (self.workdir / "ruff.toml").read_text().startswith("# aviato:managed")
        return branch

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli.GitHubPlatform, "open_worktree_proposal", fake_proposal)

    rc = main(["offboard", "acme-org/widget", "--open-pr"])
    assert rc == 0
    assert captured["repo"] == "acme-org/widget"
    assert "baseline" in captured["body"].lower() and "§2.13" in captured["body"]
    assert captured["declaration_gone"] is True
    assert captured["marker_stripped"] is True
