from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import aviato.cli as cli
from aviato.cli import main
from aviato.core.declaration import Declaration
from aviato.core.errors import AviatoError
from aviato.core.registry import Registry
from aviato.core.transition import (
    TransitionChange,
    build_transition_plan,
    execute_transition,
    inspect_transition,
    rollback_transition,
)
from aviato.paths import MODULE_SOURCE_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def _consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: v0\nvariables:\n"
        "  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )
    return tmp_path


def _invalid_consumer(tmp_path: Path) -> Path:
    github = tmp_path / ".github"
    github.mkdir()
    (github / "aviato.yaml").write_text(
        "profile: node-service\nprofile-identity: aviato-profile/node-service/v1\nversion: v0\nvariables:\n"
        "  project-name: sample\n  language-variant: ruby\n",
        encoding="utf-8",
    )
    return tmp_path


def test_legacy_sync_requires_repin_without_materializing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["sync", str(_consumer(tmp_path)), "--rebaseline-seeds"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert not (tmp_path / "ruff.toml").exists()


def test_legacy_sync_without_identity_requires_repin_without_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    declaration = consumer / ".github" / "aviato.yaml"
    declaration.write_text(declaration.read_text().replace("profile-identity: aviato-profile/python-library/v1\n", ""))
    fetched: list[str] = []

    def fake_context(_root: Path, declaration: Declaration) -> object:
        fetched.append(declaration.version)
        return SimpleNamespace(registry=Registry(MODULE_SOURCE_ROOT), policy_root=MODULE_SOURCE_ROOT)

    monkeypatch.setattr(cli, "_open_consumer_context", fake_context)
    rc = main(["sync", str(consumer), "--rebaseline-seeds"])

    assert rc == 2
    assert fetched == ["v0"]
    assert "repin" in capsys.readouterr().err
    assert "profile-identity" not in declaration.read_text()


@pytest.mark.parametrize("failure", ["unresolved", "identity-mismatch"])
def test_legacy_sync_fetch_failure_or_identity_mismatch_mutates_nothing(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer = _consumer(tmp_path)
    declaration = consumer / ".github" / "aviato.yaml"
    declaration.write_text(declaration.read_text().replace("profile-identity: aviato-profile/python-library/v1\n", ""))
    target = tmp_path / "target-library"
    shutil.copytree(MODULE_SOURCE_ROOT, target)
    if failure == "identity-mismatch":
        profile = target / "python-library.yaml"
        profile.write_text(
            profile.read_text().replace("aviato-profile/python-library/v1", "aviato-profile/repurposed/v1")
        )

    def fake_context(_root: Path, _declaration: object) -> object:
        if failure == "unresolved":
            raise AviatoError("pin does not resolve")
        raise AviatoError("profile identity mismatch")

    monkeypatch.setattr(cli, "_open_consumer_context", fake_context)
    before = {p.relative_to(consumer): p.read_bytes() for p in consumer.rglob("*") if p.is_file()}
    assert main(["sync", str(consumer), "--rebaseline-seeds"]) == 2
    after = {p.relative_to(consumer): p.read_bytes() for p in consumer.rglob("*") if p.is_file()}
    assert after == before


def test_legacy_sync_repeated_attempts_remain_non_mutating(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = _consumer(tmp_path)
    original = (consumer / ".github/aviato.yaml").read_text(encoding="utf-8")
    assert main(["sync", str(consumer), "--rebaseline-seeds"]) == 2
    capsys.readouterr()
    rc = main(["sync", str(consumer)])
    assert rc == 2
    assert "repin" in capsys.readouterr().err
    assert (consumer / ".github/aviato.yaml").read_text(encoding="utf-8") == original


def test_sync_without_declaration_fails(tmp_path: Path) -> None:
    assert main(["sync", str(tmp_path)]) != 0


def test_sync_requires_explicit_rebaseline_for_missing_seed_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    (consumer / "LICENSE").write_text("operator license\n", encoding="utf-8")

    rc = main(["sync", str(consumer)])

    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert not (consumer / "ruff.toml").exists()
    assert not (consumer / ".github" / "aviato.seed.json").exists()


def test_legacy_sync_rebaseline_requires_repin_without_seed_sidecar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    (consumer / "LICENSE").write_text("operator license\n", encoding="utf-8")
    (consumer / "pyproject.toml").write_text("operator project\n", encoding="utf-8")

    rc = main(["sync", str(consumer), "--rebaseline-seeds"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "repin" in captured.err
    assert not (consumer / ".github/aviato.seed.json").exists()


def test_schema_v2_fresh_onboard_baselines_existing_seed_atomically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "LICENSE").write_text("operator license\n", encoding="utf-8")

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
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    assert (tmp_path / "LICENSE").read_text(encoding="utf-8") == "operator license\n"
    assert (tmp_path / ".github/aviato.yaml").is_file()
    assert (tmp_path / ".github/aviato.managed.yml").is_file()
    assert "LICENSE" in (tmp_path / ".github/aviato.seed.json").read_text(encoding="utf-8")


def test_post_merge_sync_is_idempotent_with_no_stale_workflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "onboard",
                str(tmp_path),
                "--profile",
                "python-library",
                "--write",
                "--allow-dirty",
                "--pin",
                "0",
                "--var",
                "distribution-name=acme",
                "--var",
                "import-name=acme",
            ]
        )
        == 0
    )
    capsys.readouterr()
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Aviato Test",
            "-c",
            "user.email=aviato@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "onboard",
        ],
        check=True,
        capture_output=True,
    )
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tmp_path).parts
    }

    assert main(["sync", str(tmp_path)]) == 0
    assert capsys.readouterr().err == ""
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tmp_path).parts
    }
    assert after == before
    workflows = sorted(path.name for path in (tmp_path / ".github/workflows").glob("*.yml"))
    assert workflows == [
        "aviato-ci.yml",
        "aviato-drift.yml",
        "aviato-protection-checkpoint.yml",
    ]


@pytest.mark.parametrize("command", ["onboard", "sync", "repin", "offboard"])
def test_interrupted_transition_makes_each_command_print_recovery_instructions(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "onboard",
                str(tmp_path),
                "--profile",
                "python-library",
                "--write",
                "--allow-dirty",
                "--pin",
                "0",
                "--var",
                "distribution-name=acme",
                "--var",
                "import-name=acme",
            ]
        )
        == 0
    )
    capsys.readouterr()
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Aviato Test",
            "-c",
            "user.email=aviato@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "onboard",
        ],
        check=True,
        capture_output=True,
    )
    plan = build_transition_plan(
        tmp_path,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/python-library/v1",
        changes=[TransitionChange.write("interrupted.txt", b"pending\n", category="managed")],
    )

    def interrupt(phase: str, _operation: object) -> None:
        if phase == "mutation":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute_transition(plan, fault=interrupt)
    inspection = inspect_transition(tmp_path)
    assert inspection.pending

    argv = {
        "onboard": [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--pin",
            "0",
        ],
        "sync": ["sync", str(tmp_path)],
        "repin": ["repin", str(tmp_path), "0", "--write", "--override-version-pin"],
        "offboard": ["offboard", str(tmp_path), "--write"],
    }[command]
    try:
        assert main(argv) == 2
        error = capsys.readouterr().err
        assert "pending transition" in error
        assert "recover-transition" in error
    finally:
        rollback_transition(tmp_path, inspection.journal_id)


@pytest.mark.parametrize("command", ["sync", "doctor"])
def test_materialization_commands_reject_invalid_declared_enum_before_writes(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _invalid_consumer(tmp_path)
    before = {path.relative_to(consumer) for path in consumer.rglob("*")}

    rc = main([command, str(consumer), *(["--no-remote-probe"] if command == "doctor" else [])])

    captured = capsys.readouterr()
    assert rc == 2
    if command == "sync":
        assert "repin" in captured.err
    else:
        assert "language-variant" in captured.err
    assert {path.relative_to(consumer) for path in consumer.rglob("*")} == before
