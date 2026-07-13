from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import aviato.cli as cli
from aviato.cli import main
from aviato.core.errors import AviatoError
from aviato.core.onboarding import materialize_items
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT


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


def test_sync_materializes_managed_and_seed_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["sync", str(_consumer(tmp_path)), "--rebaseline-seeds"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote .editorconfig" in out
    assert "seeded LICENSE" in out
    assert (tmp_path / "ruff.toml").read_text().startswith("# aviato:managed profile=python-library version=v0")


def test_sync_backfills_legacy_identity_from_its_declared_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _consumer(tmp_path)
    declaration = consumer / ".github" / "aviato.yaml"
    declaration.write_text(declaration.read_text().replace("profile-identity: aviato-profile/python-library/v1\n", ""))
    fetched: list[str] = []

    @contextmanager
    def fake_fetch(repository: str, pin: str) -> Iterator[Registry]:
        fetched.append(pin)
        yield Registry(MODULE_SOURCE_ROOT)

    monkeypatch.setattr(cli, "fetch_library_registry", fake_fetch)
    rc = main(["sync", str(consumer), "--rebaseline-seeds"])

    assert rc == 0
    assert fetched == ["v0"]
    assert "wrote profile-identity aviato-profile/python-library/v1" in capsys.readouterr().out
    assert "profile-identity: aviato-profile/python-library/v1" in declaration.read_text()


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

    @contextmanager
    def fake_fetch(repository: str, pin: str) -> Iterator[Registry]:
        if failure == "unresolved":
            raise AviatoError("pin does not resolve")
        yield Registry(target)

    monkeypatch.setattr(cli, "fetch_library_registry", fake_fetch)
    before = {p.relative_to(consumer): p.read_bytes() for p in consumer.rglob("*") if p.is_file()}
    assert main(["sync", str(consumer), "--rebaseline-seeds"]) == 2
    after = {p.relative_to(consumer): p.read_bytes() for p in consumer.rglob("*") if p.is_file()}
    assert after == before


def test_sync_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    consumer = _consumer(tmp_path)
    main(["sync", str(consumer), "--rebaseline-seeds"])
    capsys.readouterr()
    rc = main(["sync", str(consumer)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote " not in out  # nothing rewritten on a clean tree
    assert "unchanged .editorconfig" in out


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
    assert "--rebaseline-seeds" in captured.err
    assert not (consumer / "ruff.toml").exists()
    assert not (consumer / ".github" / "aviato.seed.json").exists()


def test_sync_rebaseline_prints_every_adopted_seed_and_writes_exact_sidecar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    consumer = _consumer(tmp_path)
    (consumer / "LICENSE").write_text("operator license\n", encoding="utf-8")
    (consumer / "pyproject.toml").write_text("operator project\n", encoding="utf-8")

    rc = main(["sync", str(consumer), "--rebaseline-seeds"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "baselined LICENSE" in captured.out
    assert "baselined pyproject.toml" in captured.out
    sidecar = json.loads((consumer / ".github" / "aviato.seed.json").read_text(encoding="utf-8"))
    assert set(sidecar) == {
        item.output
        for item in materialize_items(
            Registry(MODULE_SOURCE_ROOT),
            "python-library",
            {"distribution-name": "acme", "import-name": "acme"},
            pin="v0",
        )
        if item.seed_once
    }


def test_fresh_onboard_write_baselines_preexisting_seed_before_writes(
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
            "--allow-unresolved-pin",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "baselined LICENSE" in captured.out
    assert captured.out.index("baselined LICENSE") < captured.out.index("wrote .github/aviato.yaml")


@pytest.mark.parametrize("command", ["sync", "doctor"])
def test_materialization_commands_reject_invalid_declared_enum_before_writes(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consumer = _invalid_consumer(tmp_path)
    before = {path.relative_to(consumer) for path in consumer.rglob("*")}

    rc = main([command, str(consumer), *(["--no-remote-probe"] if command == "doctor" else [])])

    captured = capsys.readouterr()
    assert rc == 2
    assert "language-variant" in captured.err
    assert {path.relative_to(consumer) for path in consumer.rglob("*")} == before
