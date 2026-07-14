from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aviato.core.errors import InventoryError
from aviato.core.inventory import (
    INVENTORY_PATH,
    InventoryEntry,
    ManagedInventory,
    load_managed_inventory,
    reconcile_managed_inventory,
    render_managed_inventory,
    scan_marker_universe,
)
from aviato.core.marker import canonical_input_hash, content_hash, render_marker

PROFILE = "python-library"
PIN = "1.2.3"
SNAPSHOT = "a" * 40
INPUT_HASH = "b" * 64


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    return root


def _managed_text(body: str, *, profile: str = PROFILE, pin: str = PIN, input_hash: str = INPUT_HASH) -> str:
    marker = render_marker(profile=profile, version=pin, body=body, comment="#", input_hash=input_hash)
    return f"{marker}\n{body}"


def _entry(
    path: str,
    body: str,
    *,
    artifact_id: str = "artifact:ci",
    aliases: tuple[str, ...] = (),
) -> InventoryEntry:
    marker_line = _managed_text(body).splitlines()[0]
    return InventoryEntry(
        artifact_id=artifact_id,
        pipeline_owners=("pipeline:verify",),
        marker_hash=content_hash(marker_line),
        body_hash=content_hash(body),
        input_hash=INPUT_HASH,
        legacy_aliases=aliases,
    )


def _inventory(entries: dict[str, InventoryEntry]) -> ManagedInventory:
    return ManagedInventory(
        schema_version=1,
        profile=PROFILE,
        profile_identity="profile:python-library",
        pin=PIN,
        snapshot_commit=SNAPSHOT,
        entries=entries,
        owned_rulesets=(),
    )


def _write_inventory(root: Path, inventory: ManagedInventory) -> None:
    path = root / INVENTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_managed_inventory(inventory), encoding="utf-8")


def test_inventory_is_schema_versioned_marker_bearing_and_does_not_list_itself(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    inventory = _inventory({".github/workflows/ci.yml": _entry(".github/workflows/ci.yml", "name: ci\n")})
    _write_inventory(root, inventory)

    text = (root / INVENTORY_PATH).read_text(encoding="utf-8")
    assert text.startswith("# aviato:managed ")
    loaded = load_managed_inventory(root)
    assert loaded.status == "valid"
    assert loaded.inventory == inventory
    assert loaded.inventory is not None
    assert loaded.inventory.schema_version == 1
    assert INVENTORY_PATH not in loaded.inventory.entries
    uppercase_inventory = root / ".github" / "AVIATO.MANAGED.YML"
    uppercase_inventory.write_text(text, encoding="utf-8")
    _git(root, "add", ".github/AVIATO.MANAGED.YML")
    assert scan_marker_universe(root) == {}
    with pytest.raises(ValueError, match="cannot list itself"):
        _inventory(
            {
                ".github/AVIATO.MANAGED.YML": _entry(
                    ".github/AVIATO.MANAGED.YML",
                    "schema_version: 1\n",
                    artifact_id="artifact:self",
                )
            }
        )


def test_marker_universe_scans_tracked_and_untracked_nonignored_git_files(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tracked = root / "tracked.yml"
    untracked = root / "untracked.yml"
    ignored = root / "ignored.yml"
    tracked.write_text(_managed_text("tracked: true\n"), encoding="utf-8")
    untracked.write_text(_managed_text("untracked: true\n"), encoding="utf-8")
    ignored.write_text(_managed_text("ignored: true\n"), encoding="utf-8")
    (root / ".gitignore").write_text("ignored.yml\n", encoding="utf-8")
    _git(root, "add", "tracked.yml", ".gitignore")

    universe = scan_marker_universe(root)

    assert set(universe) == {"tracked.yml", "untracked.yml"}
    assert all(artifact.status == "valid" for artifact in universe.values())

    nested_directory = root / "ordinary"
    nested_directory.mkdir()
    with pytest.raises(InventoryError, match="canonical Git worktree root"):
        scan_marker_universe(nested_directory)


def test_case_equivalent_git_index_entries_block_reconciliation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    lower = "flow.yml"
    upper = "FLOW.yml"
    body = "managed: true\n"
    text = _managed_text(body)
    (root / lower).write_text(text, encoding="utf-8")
    (root / upper).write_text(text, encoding="utf-8")
    blob = subprocess.run(
        ["git", "-C", str(root), "hash-object", "-w", lower],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(root, "update-index", "--add", "--cacheinfo", "100644", blob, lower)
    _git(root, "update-index", "--add", "--cacheinfo", "100644", blob, upper)
    assert {lower, upper}.issubset(scan_marker_universe(root))
    desired = _inventory({lower: _entry(lower, body, artifact_id="artifact:flow")})

    result = reconcile_managed_inventory(root, desired)

    assert len(result.obsolete_blocked) == 1
    reason = next(iter(result.obsolete_blocked.values()))
    assert "case-equivalent Git paths" in reason
    assert lower in reason and upper in reason


def test_marker_universe_excludes_git_metadata_build_roots_and_nested_worktrees(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    included = root / "managed.yml"
    included.write_text(_managed_text("ok: true\n"), encoding="utf-8")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "base.txt")
    _git(root, "-c", "user.name=Aviato Test", "-c", "user.email=aviato@example.invalid", "commit", "-qm", "base")
    for directory in ("build", "dist", "_wheelout", ".worktrees"):
        target = root / directory / "hidden.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_managed_text("hidden: true\n"), encoding="utf-8")
    nested = root / "nested"
    _git(root, "worktree", "add", "-q", "-b", "nested-worktree", str(nested))
    (nested / "hidden.yml").write_text(_managed_text("hidden: true\n"), encoding="utf-8")

    universe = scan_marker_universe(root)

    assert set(universe) == {"managed.yml"}


def test_inventory_protected_roots_and_linked_worktrees_never_gain_retirement_authority(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    hook_path = ".GIT/hooks/pre-commit"
    hook_body = "#!/bin/sh\nexit 0\n"
    hook = root / hook_path
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(_managed_text(hook_body), encoding="utf-8")
    hook_entry = _entry(hook_path, hook_body, artifact_id="artifact:hook")
    unsafe_body = (
        "schema_version: 1\n"
        f"profile: {PROFILE}\n"
        "profile_identity: profile:python-library\n"
        f"pin: {PIN}\n"
        f"snapshot_commit: {SNAPSHOT}\n"
        "entries:\n"
        f"  {hook_path}:\n"
        f"    artifact_id: {hook_entry.artifact_id}\n"
        "    pipeline_owners:\n      - pipeline:verify\n"
        f"    marker_hash: {hook_entry.marker_hash}\n"
        f"    body_hash: {hook_entry.body_hash}\n"
        f"    input_hash: {hook_entry.input_hash}\n"
        "    legacy_aliases: []\n"
        "owned_remote_resources:\n  rulesets: []\n"
    )
    unsafe_marker = render_marker(
        profile=PROFILE,
        version=PIN,
        body=unsafe_body,
        comment="#",
        input_hash=canonical_input_hash(
            {
                "profile_identity": "profile:python-library",
                "pin": PIN,
                "snapshot_commit": SNAPSHOT,
            }
        ),
    )
    inventory_path = root / INVENTORY_PATH
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(f"{unsafe_marker}\n{unsafe_body}", encoding="utf-8")
    hook_read = load_managed_inventory(root)
    assert hook_read.status == "invalid"
    assert hook_read.reason is not None and "protected" in hook_read.reason

    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "base.txt")
    _git(root, "-c", "user.name=Aviato Test", "-c", "user.email=aviato@example.invalid", "commit", "-qm", "base")
    nested = root / "nested"
    _git(root, "worktree", "add", "-q", "-b", "nested-inventory", str(nested))
    nested_path = "nested/managed.yml"
    nested_body = "managed: true\n"
    (root / nested_path).write_text(_managed_text(nested_body), encoding="utf-8")
    nested_inventory = _inventory({nested_path: _entry(nested_path, nested_body, artifact_id="artifact:nested")})
    _write_inventory(root, nested_inventory)
    nested_read = load_managed_inventory(root)
    assert nested_read.status == "invalid"
    assert nested_read.reason is not None and "nested" in nested_read.reason


@pytest.mark.parametrize("case", ["missing", "truncated", "malformed", "modified", "path_injection"])
def test_missing_truncated_malformed_modified_and_path_injecting_inventory_fail_closed(
    tmp_path: Path, case: str
) -> None:
    root = _repo(tmp_path)
    stale = root / ".github" / "workflows" / "stale.yml"
    stale.parent.mkdir(parents=True)
    stale.write_text(_managed_text("name: stale\n"), encoding="utf-8")
    if case != "missing":
        inventory = root / INVENTORY_PATH
        inventory.parent.mkdir(parents=True, exist_ok=True)
        if case == "truncated":
            body = "schema_version: 1\nentries: {"
            payload = _managed_text(body)
        elif case == "malformed":
            payload = "# aviato:managed broken\nschema_version: 1\n"
        elif case == "modified":
            payload = render_managed_inventory(_inventory({})) + "# hand edit\n"
        else:
            body = (
                "schema_version: 1\nprofile: python-library\nprofile_identity: p\npin: 1.2.3\n"
                f"snapshot_commit: {SNAPSHOT}\nentries:\n  ../escape: {{}}\n"
                "owned_remote_resources:\n  rulesets: []\n"
            )
            marker = render_marker(
                profile=PROFILE,
                version=PIN,
                body=body,
                comment="#",
                input_hash=INPUT_HASH,
            )
            payload = f"{marker}\n{body}"
        inventory.write_text(payload, encoding="utf-8")

    read = load_managed_inventory(root)
    assert read.status == ("missing" if case == "missing" else "invalid")
    if case == "path_injection":
        assert read.reason is not None and "canonical repository-relative path" in read.reason
    result = reconcile_managed_inventory(root, _inventory({}), prior=read)
    assert ".github/workflows/stale.yml" in result.obsolete_blocked
    assert not result.obsolete_clean


def test_inventory_cannot_hide_a_marked_file_it_omits(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    stale_path = ".github/workflows/stale.yml"
    stale = root / stale_path
    stale.parent.mkdir(parents=True)
    stale.write_text(_managed_text("name: stale\n"), encoding="utf-8")
    _write_inventory(root, _inventory({}))

    result = reconcile_managed_inventory(root, _inventory({}))

    assert stale_path in result.obsolete_blocked
    assert "omits" in result.obsolete_blocked[stale_path]


def test_unambiguous_legacy_marker_is_adopted_but_ambiguity_blocks(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old_path = ".github/workflows/old-ci.yml"
    old = root / old_path
    old.parent.mkdir(parents=True)
    old.write_text(_managed_text("name: old\n"), encoding="utf-8")
    desired = _inventory(
        {".github/workflows/ci.yml": _entry(".github/workflows/ci.yml", "name: ci\n", aliases=(old_path,))}
    )

    adopted = reconcile_managed_inventory(root, desired)
    assert adopted.legacy_adoptable == {old_path: "artifact:ci"}

    ambiguous = _inventory(
        {
            ".github/workflows/ci.yml": _entry(".github/workflows/ci.yml", "name: ci\n", aliases=(old_path,)),
            ".github/workflows/security.yml": _entry(
                ".github/workflows/security.yml",
                "name: security\n",
                artifact_id="artifact:security",
                aliases=(old_path,),
            ),
        }
    )
    blocked = reconcile_managed_inventory(root, ambiguous)
    assert old_path in blocked.ambiguous
    assert old_path in blocked.obsolete_blocked

    case_ambiguous = _inventory(
        {
            ".github/workflows/ci.yml": _entry(
                ".github/workflows/ci.yml",
                "name: ci\n",
                aliases=(old_path,),
            ),
            ".github/workflows/security.yml": _entry(
                ".github/workflows/security.yml",
                "name: security\n",
                artifact_id="artifact:security",
                aliases=(old_path.upper(),),
            ),
        }
    )
    case_blocked = reconcile_managed_inventory(root, case_ambiguous)
    assert not case_blocked.legacy_adoptable
    assert len(case_blocked.ambiguous) == 1
    assert set(next(iter(case_blocked.ambiguous.values()))) == {"artifact:ci", "artifact:security"}
    assert set(case_blocked.obsolete_blocked) == set(case_blocked.ambiguous)


def test_symlinked_legacy_alias_is_explicitly_blocked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    alias_path = ".github/workflows/legacy.yml"
    outside = tmp_path / "outside.yml"
    outside.write_text(_managed_text("outside: true\n"), encoding="utf-8")
    alias = root / alias_path
    alias.parent.mkdir(parents=True)
    alias.symlink_to(outside)
    desired = _inventory(
        {
            ".github/workflows/ci.yml": _entry(
                ".github/workflows/ci.yml",
                "name: ci\n",
                aliases=(alias_path,),
            )
        }
    )

    result = reconcile_managed_inventory(root, desired)

    assert alias_path in result.obsolete_blocked
    assert "symlink" in result.obsolete_blocked[alias_path]
    assert alias_path not in result.legacy_adoptable


def test_clean_obsolete_managed_artifact_is_retirable(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = ".github/workflows/old.yml"
    body = "name: old\n"
    target = root / path
    target.parent.mkdir(parents=True)
    target.write_text(_managed_text(body), encoding="utf-8")
    prior = _inventory({path: _entry(path, body, artifact_id="artifact:old")})
    _write_inventory(root, prior)

    result = reconcile_managed_inventory(root, _inventory({}))

    assert result.obsolete_clean == (path,)
    assert not result.obsolete_blocked


def test_case_equivalent_path_cannot_change_stable_artifact_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = ".github/workflows/ci.yml"
    body = "name: ci\n"
    target = root / path
    target.parent.mkdir(parents=True)
    target.write_text(_managed_text(body), encoding="utf-8")
    prior = _inventory({path: _entry(path, body, artifact_id="artifact:old-ci")})
    _write_inventory(root, prior)
    desired_path = path.upper()
    desired = _inventory(
        {
            desired_path: _entry(
                desired_path,
                "name: replacement\n",
                artifact_id="artifact:new-ci",
            )
        }
    )

    result = reconcile_managed_inventory(root, desired)

    assert path in result.obsolete_blocked
    assert "stable artifact identity" in result.obsolete_blocked[path]
    assert path not in result.obsolete_clean


def test_dirty_foreign_malformed_symlinked_or_unreadable_obsolete_artifact_blocks(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cases = {
        "dirty.yml": _managed_text("old: true\n") + "edited: true\n",
        "foreign.yml": _managed_text("foreign: true\n", profile="node-service"),
        "malformed.yml": "# aviato:managed broken\nbody: true\n",
    }
    entries: dict[str, InventoryEntry] = {}
    for name, text in cases.items():
        path = f".github/workflows/{name}"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        body = (
            "old: true\n" if name == "dirty.yml" else ("foreign: true\n" if name == "foreign.yml" else "body: true\n")
        )
        entries[path] = _entry(path, body, artifact_id=f"artifact:{name}")

    symlink_path = ".github/workflows/symlink.yml"
    outside = tmp_path / "outside.yml"
    outside.write_text(_managed_text("outside: true\n"), encoding="utf-8")
    os.symlink(outside, root / symlink_path)
    entries[symlink_path] = _entry(symlink_path, "outside: true\n", artifact_id="artifact:symlink")

    unreadable_path = ".github/workflows/unreadable.yml"
    (root / unreadable_path).write_bytes(b"# aviato:managed \xff\n")
    entries[unreadable_path] = _entry(unreadable_path, "x: true\n", artifact_id="artifact:unreadable")
    _write_inventory(root, _inventory(entries))

    result = reconcile_managed_inventory(root, _inventory({}))

    assert set(result.obsolete_blocked) == set(entries)
    assert not result.obsolete_clean


def test_missing_obsolete_artifact_drops_from_next_inventory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = ".github/workflows/gone.yml"
    _write_inventory(root, _inventory({path: _entry(path, "name: gone\n", artifact_id="artifact:gone")}))

    result = reconcile_managed_inventory(root, _inventory({}))

    assert result.obsolete_missing == (path,)
    assert path not in result.next_inventory.entries


def test_seed_once_artifact_is_never_retired_by_managed_inventory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = "LICENSE"
    body = "operator owned\n"
    (root / path).write_text(_managed_text(body), encoding="utf-8")
    _write_inventory(root, _inventory({path: _entry(path, body, artifact_id="artifact:license")}))

    result = reconcile_managed_inventory(root, _inventory({}), seed_once_paths={path})

    assert path in result.obsolete_blocked
    assert "seed-once" in result.obsolete_blocked[path]
    assert path not in result.obsolete_clean

    alias_path = "legacy-license.txt"
    (root / alias_path).write_text(_managed_text("legacy operator file\n"), encoding="utf-8")
    desired = _inventory(
        {
            "LICENSE.new": _entry(
                "LICENSE.new",
                "new\n",
                artifact_id="artifact:new-license",
                aliases=(alias_path,),
            )
        }
    )
    alias_result = reconcile_managed_inventory(root, desired, seed_once_paths={alias_path})
    assert alias_path in alias_result.obsolete_blocked
    assert alias_path not in alias_result.legacy_adoptable
