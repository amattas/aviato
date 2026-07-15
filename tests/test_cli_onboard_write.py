from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import aviato.cli as cli
from aviato.cli import main
from aviato.core.declaration import Declaration
from aviato.core.inventory import ManagedInventory, render_managed_inventory
from aviato.core.registry import Registry
from aviato.paths import MODULE_SOURCE_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def _git_init_clean(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    # An empty repo with no changes is a clean working tree.


def _write_legacy_declaration(tmp_path: Path, *, profile: str = "python-library", docs: bool = False) -> Path:
    declaration = tmp_path / ".github/aviato.yaml"
    declaration.parent.mkdir(parents=True, exist_ok=True)
    declaration.write_text(
        yaml.safe_dump(
            {
                "profile": profile,
                "profile-identity": f"aviato-profile/{profile}/v1",
                "version": "0",
                "docs": docs,
                "variables": {"distribution-name": "acme", "import-name": "acme"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return declaration


def test_profile_migration_opens_the_inventory_recorded_source_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_registry = Registry(MODULE_SOURCE_ROOT)
    target_registry = Registry(MODULE_SOURCE_ROOT)
    identity = source_registry.profile("python-library").identity
    inventory = ManagedInventory(
        schema_version=1,
        profile="python-library",
        profile_identity=identity,
        pin="0",
        snapshot_commit="a" * 40,
        entries={},
    )
    inventory_path = tmp_path / ".github/aviato.managed.yml"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(render_managed_inventory(inventory), encoding="utf-8")
    declaration = Declaration(
        profile="python-library",
        profile_identity=identity,
        version="0",
        variables={"distribution-name": "acme", "import-name": "acme"},
    )
    target_context = SimpleNamespace(
        snapshot=SimpleNamespace(commit_sha="b" * 40, registry=target_registry),
        registry=target_registry,
    )
    opened: list[tuple[str, str]] = []

    def open_recorded(commit_sha: str, *, requested_pin: str) -> SimpleNamespace:
        opened.append((commit_sha, requested_pin))
        return SimpleNamespace(commit_sha=commit_sha, registry=source_registry)

    monkeypatch.setattr(cli, "_open_recorded_snapshot", open_recorded)

    selected = cli._migration_source_registry(tmp_path, declaration, target_context)

    assert selected is source_registry
    assert opened == [("a" * 40, "0")]


def test_schema_v2_fresh_write_creates_declaration_and_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert (tmp_path / ".github/aviato.yaml").is_file()
    assert (tmp_path / ".github/aviato.managed.yml").is_file()


def test_local_collision_cannot_write_declaration_then_return_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "ruff.toml").write_text("operator-owned\n", encoding="utf-8")

    rc = main(
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

    assert rc == 2
    assert "ruff.toml" in capsys.readouterr().err
    assert not (tmp_path / ".github/aviato.yaml").exists()
    assert not (tmp_path / ".github/aviato.managed.yml").exists()
    assert (tmp_path / "ruff.toml").read_text(encoding="utf-8") == "operator-owned\n"


@pytest.mark.parametrize("sidecar_body", ["{}\n", "{ corrupt"])
def test_onboard_write_does_not_treat_lost_declaration_as_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sidecar_body: str
) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    sidecar = github / "aviato.seed.json"
    sidecar.write_text(sidecar_body, encoding="utf-8")
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
            "0",
            "--var",
            "distribution-name=acme",
            "--var",
            "import-name=acme",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "--rebaseline-seeds" in captured.err
    assert not (github / "aviato.yaml").exists()
    assert not (tmp_path / "ruff.toml").exists()
    assert sidecar.read_text(encoding="utf-8") == sidecar_body
    assert (tmp_path / "LICENSE").read_text(encoding="utf-8") == "operator license\n"


def test_legacy_reonboard_preserves_docs_while_requiring_repin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.2/§6.1 (M-D): re-onboarding an adopted docs:true repo WITHOUT --docs must NOT silently
    # flip docs back to false. --docs only enables; a re-run preserves the existing choice.
    base = [
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
    declaration = _write_legacy_declaration(tmp_path, docs=True)
    original = declaration.read_text(encoding="utf-8")
    assert main(base) == 2
    assert "repin" in capsys.readouterr().err
    assert declaration.read_text(encoding="utf-8") == original


def test_legacy_reonboard_docs_true_requires_repin_without_scaffolding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # §5.2/§6.1/§13.3 (FIX-1): a docs:true declaration re-onboarded WITHOUT --docs must keep
    # docs:true AND scaffold the docs workflow — the artifacts must match the declaration, not
    # silently omit docs (the partial-fix bug where scaffold used args.docs).
    base = [
        "onboard",
        str(tmp_path),
        "--profile",
        "python-library",
        "--write",
        "--allow-dirty",
        "--pin",
        "0",
        "--var",
        "distribution-name=a",
        "--var",
        "import-name=a",
    ]
    declaration = _write_legacy_declaration(tmp_path, docs=True)
    original = declaration.read_text(encoding="utf-8")
    assert main(base) == 2
    assert "repin" in capsys.readouterr().err
    assert declaration.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".github/workflows").exists()


def test_onboard_write_fails_on_missing_required_var(tmp_path: Path) -> None:
    rc = main(["onboard", str(tmp_path), "--profile", "python-library", "--write", "--pin", "0"])
    assert rc == 2
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_fresh_onboard_write_requires_explicit_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "--pin" in err
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_fresh_onboard_write_refuses_unpublished_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aviato.core.errors import AviatoError

    monkeypatch.setattr(
        cli,
        "_open_new_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AviatoError("Library pin '0' does not resolve")),
    )
    rc = main(
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
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not resolve" in err
    assert "does not resolve" in err
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_onboard_write_refuses_profile_change_without_migrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = tmp_path / ".github"
    github.mkdir()
    declaration = github / "aviato.yaml"
    original = "profile: node-service\nprofile-identity: aviato-profile/node-service/v1\nversion: v0\n"
    declaration.write_text(original, encoding="utf-8")
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 2
    assert "--migrate-profile" in capsys.readouterr().err
    assert declaration.read_text(encoding="utf-8") == original


def test_legacy_onboard_write_profile_migration_requires_repin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    declaration_path = _write_legacy_declaration(tmp_path)
    original = declaration_path.read_text(encoding="utf-8")

    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "node-service",
            "--write",
            "--allow-dirty",
            "--pin",
            "0",
            "--migrate-profile",
            "--var",
            "project-name=widget",
            "--var",
            "language-variant=typescript",
        ]
    )

    assert rc == 2
    assert "repin" in capsys.readouterr().err
    assert declaration_path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "eslint.config.mjs").exists()


@pytest.mark.parametrize(
    ("target_state", "reason"),
    [
        ("unmanaged", "unmanaged"),
        ("malformed", "malformed"),
        ("unrelated-profile", "does not match"),
        ("unknown-version", "unknown version"),
        ("hand-edited", "hand-edited"),
    ],
)
def test_onboard_write_profile_migration_protects_target_and_mutates_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target_state: str,
    reason: str,
) -> None:
    _write_legacy_declaration(tmp_path)
    target = tmp_path / ".editorconfig"
    replacements = {
        "unmanaged": "operator-owned\n",
        "malformed": "# aviato:managed malformed\nbody\n",
        "unrelated-profile": "# aviato:managed profile=swift-app version=0 hash=abc\nbody\n",
        "unknown-version": "# aviato:managed profile=python-library version=unknown hash=abc\nbody\n",
        "hand-edited": "# aviato:managed profile=python-library version=0 hash=abc\n# operator edit\n",
    }
    target.write_text(replacements[target_state], encoding="utf-8")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "node-service",
            "--write",
            "--allow-dirty",
            "--pin",
            "0",
            "--migrate-profile",
            "--var",
            "project-name=widget",
            "--var",
            "language-variant=typescript",
        ]
    )

    captured = capsys.readouterr()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert rc == 2
    assert "repin" in captured.err
    assert after == before


def test_onboard_write_profile_migration_scaffold_rechecks_before_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_legacy_declaration(tmp_path)
    (tmp_path / ".editorconfig").write_text("operator-owned\n", encoding="utf-8")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "node-service",
            "--write",
            "--allow-dirty",
            "--pin",
            "0",
            "--migrate-profile",
            "--var",
            "project-name=widget",
            "--var",
            "language-variant=typescript",
        ]
    )

    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert rc == 2
    assert "repin" in capsys.readouterr().err
    assert after == before


def test_onboard_write_refuses_dirty_tree_without_override(tmp_path: Path) -> None:
    # §5.2 adopt precondition: a non-clean working tree is refused unless --allow-dirty.
    _git_init_clean(tmp_path)
    (tmp_path / "untracked.txt").write_text("dirty", encoding="utf-8")
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--pin",
            "0",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 2
    assert not (tmp_path / ".github" / "aviato.yaml").exists()


def test_schema_v2_onboard_write_clean_git_repo_succeeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git_init_clean(tmp_path)
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--pin",
            "0",
            "--var",
            "distribution-name=a",
            "--var",
            "import-name=a",
        ]
    )
    assert rc == 0
    assert capsys.readouterr().err == ""
    assert (tmp_path / ".github" / "aviato.yaml").is_file()
    assert (tmp_path / ".github" / "aviato.managed.yml").is_file()


def test_onboard_without_write_only_prints_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["onboard", str(tmp_path), "--profile", "python-library", "--pin", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Onboarding plan" in out
    assert not (tmp_path / ".github" / "aviato.yaml").exists()  # plan-only, no write


@pytest.mark.parametrize("identity_line", ["", "profile-identity: aviato-profile/repurposed/v1\n"])
def test_reonboard_write_refuses_legacy_or_mismatched_identity_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], identity_line: str
) -> None:
    declaration = tmp_path / ".github" / "aviato.yaml"
    declaration.parent.mkdir()
    original = (
        "profile: python-library\n"
        f"{identity_line}"
        "version: 0\nvariables:\n  distribution-name: acme\n  import-name: acme\n"
    )
    declaration.write_text(original, encoding="utf-8")

    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--write",
            "--allow-dirty",
            "--pin",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "profile identity" in captured.err.lower()
    if identity_line:
        assert "mismatch" in captured.err.lower()
    else:
        assert "aviato sync" in captured.err
    assert declaration.read_text(encoding="utf-8") == original
    assert not (tmp_path / "ruff.toml").exists()
