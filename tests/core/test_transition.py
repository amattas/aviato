from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from aviato.core import transition as transition_module
from aviato.core.inventory import InventoryEntry, ManagedInventory, render_managed_inventory
from aviato.core.marker import canonical_input_hash, content_hash, marker_line_from_text
from aviato.core.outcomes import OperationStatus
from aviato.core.scaffold import ScaffoldItem, inventory_entry_for_item, render_managed
from aviato.core.transition import (
    TransitionChange,
    TransitionConflictError,
    TransitionExecutionError,
    TransitionPlan,
    TransitionRecoveryError,
    build_transition_plan,
    execute_transition,
    inspect_transition,
    plan_transition,
    resume_pending_transition,
    resume_transition,
    rollback_transition,
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "transition@example.com")
    _git(tmp_path, "config", "user.name", "Transition Test")
    return tmp_path


def _plan(
    repo: Path,
    *changes: TransitionChange,
    allow_dirty: bool = True,
) -> TransitionPlan:
    return build_transition_plan(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/test/v1",
        changes=changes,
        allow_dirty=allow_dirty,
    )


def _commit_fixture(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")


def test_transition_plan_is_pure_complete_deterministic_and_digest_bound(repo: Path) -> None:
    original = b"old\r\n"
    (repo / "managed.txt").write_bytes(original)
    before = sorted(str(path.relative_to(repo)) for path in repo.rglob("*") if ".git" not in path.parts)
    changes = (
        TransitionChange.write(".github/aviato.managed.yml", b"inventory\n", category="inventory"),
        TransitionChange.write("managed.txt", b"new\r\n", category="managed"),
        TransitionChange.write(".github/aviato.yaml", b"profile: test\n", category="declaration"),
        TransitionChange.write("seed.txt", b"seed\n", category="seed"),
    )

    first = _plan(repo, *changes)
    second = _plan(repo, *reversed(changes))

    assert first == second
    assert first.digest == second.digest
    assert [operation.category for operation in first.operations] == [
        "managed",
        "seed",
        "declaration",
        "inventory",
    ]
    assert first.operations[0].desired_bytes == b"new\r\n"
    assert first.operations[0].expected.sha256
    assert first.operations[0].mode == stat.S_IMODE((repo / "managed.txt").stat().st_mode)
    assert sorted(str(path.relative_to(repo)) for path in repo.rglob("*") if ".git" not in path.parts) == before
    assert not inspect_transition(repo).pending

    changed = _plan(
        repo,
        TransitionChange.write("managed.txt", b"different\n", category="managed"),
    )
    assert changed.digest != first.digest


def test_executor_rejects_a_plan_whose_payload_no_longer_matches_its_digest(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"approved\n", category="managed"))
    operation = replace(plan.operations[0], desired_bytes=b"evil\n")
    confused = replace(plan, operations=(operation,))

    with pytest.raises(TransitionConflictError, match="digest"):
        execute_transition(confused)

    assert not (repo / "managed.txt").exists()


def test_transition_conflict_preflight_performs_no_mutation(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"operator owned\n")
    plan = build_transition_plan(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="id",
        changes=(TransitionChange.write("managed.txt", b"desired\n", category="managed"),),
        conflicts=("managed.txt is operator-owned",),
        allow_dirty=True,
    )

    with pytest.raises(TransitionConflictError, match="operator-owned"):
        execute_transition(plan)

    assert target.read_bytes() == b"operator owned\n"
    assert not inspect_transition(repo).pending


def test_allow_dirty_never_allows_overlap_with_a_planned_path(repo: Path) -> None:
    (repo / "planned.txt").write_text("tracked\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    (repo / "planned.txt").write_text("operator edit\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("unrelated edit\n", encoding="utf-8")

    plan = _plan(
        repo,
        TransitionChange.write("planned.txt", b"desired\n", category="managed"),
        allow_dirty=True,
    )
    assert any("planned.txt" in conflict for conflict in plan.conflicts)

    unrelated = _plan(
        repo,
        TransitionChange.write("new.txt", b"desired\n", category="managed"),
        allow_dirty=True,
    )
    assert not unrelated.conflicts


def test_executor_reconfines_and_refingerprints_every_path_before_mutation(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    target.write_bytes(b"raced\n")

    with pytest.raises(TransitionConflictError, match="fingerprint"):
        execute_transition(plan)

    assert target.read_bytes() == b"raced\n"
    assert not inspect_transition(repo).pending


def test_executor_orders_managed_changes_then_sidecar_declaration_and_inventory_last(repo: Path) -> None:
    phases: list[tuple[str, str]] = []
    inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="aviato-profile/test/v1",
        pin="0",
        snapshot_commit="a" * 40,
    )
    plan = _plan(
        repo,
        TransitionChange.write(
            ".github/aviato.managed.yml",
            render_managed_inventory(inventory).encode(),
            category="inventory",
        ),
        TransitionChange.write(".github/aviato.yaml", b"declaration\n", category="declaration"),
        TransitionChange.write(".github/aviato.seed.json", b"{}\n", category="sidecar"),
        TransitionChange.write("managed.txt", b"managed\n", category="managed"),
    )

    result = execute_transition(
        plan,
        fault=lambda phase, operation: phases.append((phase, operation.path if operation else "")),
    )

    assert result.success
    assert [path for phase, path in phases if phase == "applied_fsync"] == [
        "managed.txt",
        ".github/aviato.seed.json",
        ".github/aviato.yaml",
        ".github/aviato.managed.yml",
    ]


def test_high_level_transition_plans_seed_sidecar_declaration_and_inventory_together(repo: Path) -> None:
    managed = ScaffoldItem(
        "managed.yml",
        "name: managed\n",
        "#",
        input_hash=canonical_input_hash({"fixture": True}),
        artifact_id="artifact/managed/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )
    seed = ScaffoldItem(
        "LICENSE",
        "seed\n",
        "#",
        seed_once=True,
        input_hash=canonical_input_hash({"fixture": True}),
        artifact_id="artifact/license/v1",
    )

    prepared = plan_transition(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="0",
        items=(managed, seed),
        declaration_bytes=b"profile: test\n",
        baseline_existing_seeds=True,
        allow_fresh_seed_initialization=True,
    )

    assert [operation.category for operation in prepared.plan.operations] == [
        "managed",
        "seed",
        "sidecar",
        "declaration",
        "inventory",
    ]
    assert execute_transition(prepared.plan).success
    assert (repo / "managed.yml").exists()
    assert (repo / "LICENSE").read_bytes() == b"seed\n"
    assert (repo / ".github/aviato.seed.json").is_file()
    assert (repo / ".github/aviato.yaml").is_file()
    assert (repo / ".github/aviato.managed.yml").is_file()


def test_high_level_transition_collision_blocks_before_declaration_write(repo: Path) -> None:
    (repo / "managed.yml").write_text("operator-owned\n")
    managed = ScaffoldItem(
        "managed.yml",
        "name: managed\n",
        "#",
        input_hash=canonical_input_hash({"fixture": True}),
        artifact_id="artifact/managed/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )

    prepared = plan_transition(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="0",
        items=(managed,),
        declaration_bytes=b"profile: test\n",
    )

    with pytest.raises(TransitionConflictError, match="unmanaged"):
        execute_transition(prepared.plan)
    assert not (repo / ".github/aviato.yaml").exists()
    assert not (repo / ".github/aviato.managed.yml").exists()


def test_fresh_transition_never_overwrites_an_operator_owned_inventory(repo: Path) -> None:
    inventory = repo / ".github/aviato.managed.yml"
    inventory.parent.mkdir(parents=True)
    inventory.write_text("operator-owned\n", encoding="utf-8")

    prepared = plan_transition(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="0",
        items=(),
        declaration_bytes=b"profile: test\n",
        allow_dirty=True,
    )

    assert any("inventory is invalid or operator-owned" in conflict for conflict in prepared.plan.conflicts)
    with pytest.raises(TransitionConflictError):
        execute_transition(prepared.plan)
    assert inventory.read_text(encoding="utf-8") == "operator-owned\n"
    assert not (repo / ".github/aviato.yaml").exists()


def test_legacy_source_inventory_retires_artifact_removed_from_target_snapshot(repo: Path) -> None:
    old = ScaffoldItem(
        "obsolete.yml",
        "name: obsolete\n",
        "#",
        input_hash=canonical_input_hash({"artifact": "obsolete"}),
        artifact_id="artifact/obsolete/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )
    (repo / "obsolete.yml").write_text(render_managed(old, profile="test", version="0"), encoding="utf-8")
    (repo / ".github").mkdir()
    (repo / ".github/aviato.yaml").write_text("profile: test\nversion: 0\n", encoding="utf-8")
    _commit_fixture(repo)
    source_inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="aviato-profile/test/v1",
        pin="0",
        snapshot_commit="a" * 40,
        entries={"obsolete.yml": inventory_entry_for_item(old, profile="test", version="0")},
    )

    prepared = plan_transition(
        repo,
        snapshot_sha="b" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="1",
        items=(),
        declaration_bytes=b"profile: test\nversion: 1\n",
        source_inventory=source_inventory,
        allow_dirty=True,
    )

    assert prepared.plan.conflicts == ()
    assert prepared.retired == ("obsolete.yml",)
    execute_transition(prepared.plan)
    assert not (repo / "obsolete.yml").exists()


def test_profile_migration_rejects_live_body_that_only_matches_new_desired_body(repo: Path) -> None:
    old = ScaffoldItem(
        "managed.yml",
        "old body\n",
        "#",
        input_hash=canonical_input_hash({"artifact": "managed"}),
        artifact_id="artifact/managed/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )
    new = replace(old, body="new desired body\n")
    live = render_managed(old, profile="old-profile", version="0").replace("old body\n", new.body)
    (repo / "managed.yml").write_text(live, encoding="utf-8")

    prepared = plan_transition(
        repo,
        snapshot_sha="b" * 40,
        declaration_identity="aviato-profile/new/v1",
        profile="new-profile",
        pin="1",
        items=(new,),
        declaration_bytes=b"profile: new-profile\nversion: 1\n",
        migrating_from="old-profile",
        allow_dirty=True,
    )

    assert any("hand-edited" in conflict for conflict in prepared.plan.conflicts)


def test_sync_and_repin_retire_only_clean_prior_snapshot_artifacts(repo: Path) -> None:
    old = ScaffoldItem(
        "obsolete.yml",
        "name: obsolete\n",
        "#",
        input_hash=canonical_input_hash({"artifact": "obsolete"}),
        artifact_id="artifact/obsolete/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )
    kept = ScaffoldItem(
        "kept.yml",
        "name: kept\n",
        "#",
        input_hash=canonical_input_hash({"artifact": "kept"}),
        artifact_id="artifact/kept/v1",
        pipeline_owners=("pipeline/verify/v2",),
    )
    initial = plan_transition(
        repo,
        snapshot_sha="a" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="0",
        items=(old, kept),
        declaration_bytes=b"profile: test\nversion: 0\n",
        baseline_existing_seeds=True,
        allow_fresh_seed_initialization=True,
    )
    execute_transition(initial.plan)
    _commit_fixture(repo)
    obsolete = repo / "obsolete.yml"
    clean = obsolete.read_bytes()
    obsolete.write_bytes(clean + b"# operator edit\n")

    blocked = plan_transition(
        repo,
        snapshot_sha="b" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="1",
        items=(kept,),
        declaration_bytes=b"profile: test\nversion: 1\n",
        allow_dirty=True,
    )
    assert any("obsolete body is modified" in conflict for conflict in blocked.plan.conflicts)
    with pytest.raises(TransitionConflictError):
        execute_transition(blocked.plan)
    assert obsolete.exists()

    obsolete.write_bytes(clean)
    converged = plan_transition(
        repo,
        snapshot_sha="b" * 40,
        declaration_identity="aviato-profile/test/v1",
        profile="test",
        pin="1",
        items=(kept,),
        declaration_bytes=b"profile: test\nversion: 1\n",
        allow_dirty=True,
    )
    assert converged.plan.conflicts == ()
    assert "obsolete.yml" in converged.retired
    execute_transition(converged.plan)
    assert not obsolete.exists()


def test_executor_preserves_mode_line_endings_and_atomic_replacement(repo: Path) -> None:
    target = repo / "script.sh"
    target.write_bytes(b"#!/bin/sh\r\necho old\r\n")
    target.chmod(0o751)
    _commit_fixture(repo)
    inode = target.stat().st_ino
    plan = _plan(
        repo,
        TransitionChange.write("script.sh", b"#!/bin/sh\r\necho new\r\n", category="managed"),
    )

    assert execute_transition(plan).success
    assert target.read_bytes() == b"#!/bin/sh\r\necho new\r\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o751
    assert target.stat().st_ino != inode


def test_ordinary_failure_rolls_back_preimages_and_verifies_semantics(repo: Path) -> None:
    first = repo / "first.txt"
    second = repo / "second.txt"
    first.write_bytes(b"one\n")
    second.write_bytes(b"two\n")
    _commit_fixture(repo)
    plan = _plan(
        repo,
        TransitionChange.write("first.txt", b"ONE\n", category="managed"),
        TransitionChange.write("second.txt", b"TWO\n", category="managed"),
    )

    def fail(phase: str, operation: object) -> None:
        if phase == "prepared_fsync" and getattr(operation, "path", None) == "second.txt":
            raise RuntimeError("ordinary injected failure")

    with pytest.raises(TransitionExecutionError) as exc_info:
        execute_transition(plan, fault=fail)

    assert first.read_bytes() == b"one\n"
    assert second.read_bytes() == b"two\n"
    assert not inspect_transition(repo).pending
    statuses = [item.status for item in exc_info.value.result.operations]
    assert OperationStatus.FAILED in statuses
    assert all(status in {OperationStatus.FAILED, OperationStatus.UNATTEMPTED} for status in statuses)
    follow_up = _plan(repo, TransitionChange.write("third.txt", b"three\n", category="managed"))
    assert execute_transition(follow_up).success


@pytest.mark.parametrize(
    "boundary",
    [
        "journal_dir_fsync",
        "manifest_fsync",
        "preimage_created",
        "preimage_fsync",
        "backup_dir_fsync",
        "prepared_fsync",
        "temp_created",
        "temp_fsync",
        "before_mutation_syscall",
        "mutation",
        "target_dir_fsync",
        "applied_fsync",
    ],
)
def test_interruption_at_each_operation_boundary_leaves_honest_recoverable_journal(repo: Path, boundary: str) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))

    def interrupt(phase: str, _operation: object) -> None:
        if phase == boundary:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execute_transition(plan, fault=interrupt)

    inspection = inspect_transition(repo)
    assert inspection.pending
    assert inspection.journal_id
    assert inspection.operations[0].status is OperationStatus.INDETERMINATE
    assert target.read_bytes() in {b"before\n", b"after\n"}
    rollback_transition(repo, inspection.journal_id)
    assert target.read_bytes() == b"before\n"


def test_same_plan_resumes_only_from_preimage_or_desired_fingerprint(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))

    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    inspection = inspect_transition(repo)
    assert resume_transition(plan, inspection.journal_id).success
    assert target.read_bytes() == b"after\n"


def test_different_plan_requires_explicit_rollback_or_recovery(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    original = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            original,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    different = _plan(repo, TransitionChange.write("managed.txt", b"other\n", category="managed"))

    with pytest.raises(TransitionRecoveryError, match="different plan"):
        execute_transition(different)

    pending = inspect_transition(repo)
    rollback_transition(repo, pending.journal_id)
    assert not inspect_transition(repo).pending


def test_recovery_refuses_path_matching_neither_preimage_nor_desired_state(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    target.write_bytes(b"operator edit\n")
    pending = inspect_transition(repo)

    with pytest.raises(TransitionRecoveryError, match="neither preimage nor desired"):
        resume_transition(plan, pending.journal_id)
    with pytest.raises(TransitionRecoveryError, match="neither preimage nor desired"):
        rollback_transition(repo, pending.journal_id)


def test_success_requires_final_diagnosis_before_journal_removal(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    seen_pending: list[bool] = []

    def validate(root: Path, _plan_value: object) -> bool:
        seen_pending.append(inspect_transition(root).pending)
        return (root / "managed.txt").read_bytes() == b"after\n"

    result = execute_transition(plan, validate=validate)
    assert result.success
    assert seen_pending == [True]
    assert not inspect_transition(repo).pending


def test_final_validation_rejects_a_marked_path_omitted_from_inventory(repo: Path) -> None:
    stale = ScaffoldItem(
        "stale.yml",
        "name: stale\n",
        "#",
        input_hash=canonical_input_hash({"fixture": True}),
    )
    (repo / "stale.yml").write_text(render_managed(stale, profile="test", version="0"))
    _commit_fixture(repo)
    inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="aviato-profile/test/v1",
        pin="0",
        snapshot_commit="a" * 40,
    )
    plan = _plan(
        repo,
        TransitionChange.write(
            ".github/aviato.managed.yml",
            render_managed_inventory(inventory).encode(),
            category="inventory",
        ),
    )

    with pytest.raises(TransitionExecutionError, match="diagnosis"):
        execute_transition(plan)

    assert not (repo / ".github/aviato.managed.yml").exists()
    assert (repo / "stale.yml").exists()


def test_final_validation_accepts_clean_inventory_deletion_only_after_markers_are_gone(repo: Path) -> None:
    inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="aviato-profile/test/v1",
        pin="0",
        snapshot_commit="a" * 40,
    )
    target = repo / ".github/aviato.managed.yml"
    target.parent.mkdir()
    target.write_text(render_managed_inventory(inventory))
    _commit_fixture(repo)

    plan = _plan(repo, TransitionChange.delete(".github/aviato.managed.yml", category="inventory"))

    assert execute_transition(plan).success
    assert not target.exists()


def test_final_validation_rejects_marker_whose_embedded_hash_disagrees_with_live_body(repo: Path) -> None:
    input_hash = canonical_input_hash({"fixture": True})
    item = ScaffoldItem("managed.yml", "name: managed\n", "#", input_hash=input_hash)
    rendered = render_managed(item, profile="test", version="0")
    marker, body = rendered.split("\n", 1)
    bad_marker = marker.replace(f"hash={content_hash(body)}", f"hash={'d' * 64}")
    malformed = f"{bad_marker}\n{body}"
    marker_line = marker_line_from_text(malformed)
    assert marker_line is not None
    (repo / "managed.yml").write_text(malformed)
    _commit_fixture(repo)
    inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="aviato-profile/test/v1",
        pin="0",
        snapshot_commit="a" * 40,
        entries={
            "managed.yml": InventoryEntry(
                artifact_id="managed",
                pipeline_owners=("fixture",),
                marker_hash=content_hash(marker_line),
                body_hash=content_hash(body),
                input_hash=input_hash,
            )
        },
    )
    plan = _plan(
        repo,
        TransitionChange.write(
            ".github/aviato.managed.yml",
            render_managed_inventory(inventory).encode(),
            category="inventory",
        ),
    )

    with pytest.raises(TransitionExecutionError, match="diagnosis"):
        execute_transition(plan)


def test_final_validation_binds_inventory_provenance_to_plan(repo: Path) -> None:
    inventory = ManagedInventory(
        schema_version=1,
        profile="test",
        profile_identity="different-profile-identity",
        pin="0",
        snapshot_commit="b" * 40,
    )
    plan = _plan(
        repo,
        TransitionChange.write(
            ".github/aviato.managed.yml",
            render_managed_inventory(inventory).encode(),
            category="inventory",
        ),
    )

    with pytest.raises(TransitionExecutionError, match="diagnosis"):
        execute_transition(plan)


def test_git_private_state_rejects_a_symlink_outside_git_administration(repo: Path) -> None:
    outside = repo.parent / f"{repo.name}-outside-state"
    outside.mkdir()
    (repo / ".git/aviato-transitions").symlink_to(outside, target_is_directory=True)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))

    with pytest.raises(TransitionRecoveryError, match="escapes|no-follow directory"):
        execute_transition(plan)

    assert list(outside.iterdir()) == []
    assert not (repo / "managed.txt").exists()


def test_rollback_skips_unattempted_noop_operations_without_preimages(repo: Path) -> None:
    (repo / "a.txt").write_bytes(b"old\n")
    (repo / "b.txt").write_bytes(b"old\n")
    (repo / "c.txt").write_bytes(b"same\n")
    _commit_fixture(repo)
    plan = _plan(
        repo,
        TransitionChange.write("a.txt", b"new\n", category="managed"),
        TransitionChange.write("b.txt", b"new\n", category="managed"),
        TransitionChange.write("c.txt", b"same\n", category="managed"),
    )

    def fail(phase: str, operation: object) -> None:
        if phase == "prepared_fsync" and getattr(operation, "path", None) == "b.txt":
            raise RuntimeError("stop before c")

    with pytest.raises(TransitionExecutionError):
        execute_transition(plan, fault=fail)

    assert (repo / "a.txt").read_bytes() == b"old\n"
    assert (repo / "b.txt").read_bytes() == b"old\n"
    assert (repo / "c.txt").read_bytes() == b"same\n"
    assert not inspect_transition(repo).pending


def test_resume_truncates_a_torn_wal_tail_before_appending(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    inspection = inspect_transition(repo)
    state, _git_dir, _namespace = transition_module._state_paths(repo)
    events = state / "journals" / inspection.journal_id / "events.jsonl"
    with events.open("ab") as handle:
        handle.write(b'{"torn":')
        handle.flush()
        os.fsync(handle.fileno())

    assert resume_transition(plan, inspection.journal_id).success
    assert (repo / "managed.txt").read_bytes() == b"desired\n"
    assert not inspect_transition(repo).pending


def test_resume_recreates_a_torn_journal_owned_preimage_while_target_is_expected(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "preimage_created" else None
            ),
        )

    inspection = inspect_transition(repo)
    assert resume_pending_transition(repo, inspection.journal_id).success
    assert target.read_bytes() == b"after\n"
    assert not inspect_transition(repo).pending


def test_resume_discards_a_torn_journal_authenticated_target_temp(repo: Path) -> None:
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed.txt", b"after\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "temp_created" else None
            ),
        )

    inspection = inspect_transition(repo)
    assert resume_pending_transition(repo, inspection.journal_id).success
    assert target.read_bytes() == b"after\n"
    assert not list(repo.glob(".aviato-transition-*.tmp"))


def test_rollback_rejects_tampered_created_directory_metadata(repo: Path) -> None:
    unrelated = repo / "operator-empty"
    unrelated.mkdir()
    plan = _plan(repo, TransitionChange.write("nested/managed.txt", b"desired\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (_ for _ in ()).throw(KeyboardInterrupt) if phase == "mutation" else None,
        )
    inspection = inspect_transition(repo)
    state, _git_dir, _namespace = transition_module._state_paths(repo)
    manifest_path = state / "journals" / inspection.journal_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["created_dirs"] = ["operator-empty"]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(TransitionRecoveryError, match="manifest digest"):
        rollback_transition(repo, inspection.journal_id)

    assert unrelated.is_dir()


def test_terminal_cleanup_failure_remains_visible_and_resumable(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))

    with pytest.raises(TransitionExecutionError):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(RuntimeError("cleanup failed")) if phase == "journal_terminal_fsync" else None
            ),
        )

    inspection = inspect_transition(repo)
    assert inspection.pending
    assert all(operation.status is OperationStatus.COMPLETED for operation in inspection.operations)
    assert (repo / "managed.txt").read_bytes() == b"desired\n"
    assert resume_pending_transition(repo, inspection.journal_id).success
    assert (repo / "managed.txt").read_bytes() == b"desired\n"
    assert not inspect_transition(repo).pending


def test_accepted_fsync_exception_never_rolls_back_durable_acceptance(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))

    with pytest.raises(TransitionExecutionError, match="accepted"):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(RuntimeError("post-fsync failure")) if phase == "accepted_fsync" else None
            ),
        )

    assert (repo / "managed.txt").read_bytes() == b"desired\n"
    inspection = inspect_transition(repo)
    assert inspection.pending
    assert all(operation.status is OperationStatus.COMPLETED for operation in inspection.operations)
    assert resume_pending_transition(repo, inspection.journal_id).success


def test_authenticated_temp_collision_never_deletes_operator_file(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))
    operator_temp: Path | None = None

    def collide(phase: str, _operation: object) -> None:
        nonlocal operator_temp
        if phase != "prepared_fsync":
            return
        inspection = inspect_transition(repo)
        state, _git_dir, _namespace = transition_module._state_paths(repo)
        events_path = state / "journals" / inspection.journal_id / "events.jsonl"
        event = json.loads(events_path.read_text().splitlines()[-1])
        operator_temp = repo / event["temp_name"]
        operator_temp.write_bytes(b"operator-owned\n")

    with pytest.raises(TransitionExecutionError, match="rolled back"):
        execute_transition(plan, fault=collide)

    assert operator_temp is not None
    assert operator_temp.read_bytes() == b"operator-owned\n"
    assert not inspect_transition(repo).pending
    operator_temp.unlink()


def test_retained_journal_dirfd_prevents_swap_from_redirecting_private_writes(repo: Path) -> None:
    with transition_module._transition_lock(repo, recovery=False):
        pass
    state, _git_dir, _namespace = transition_module._state_paths(repo)
    journals = state / "journals"
    retained = state / "journals-retained"
    outside = repo.parent / f"{repo.name}-outside-journals"
    outside.mkdir()
    swapped = False

    def swap(phase: str, _operation: object) -> None:
        nonlocal swapped
        if phase == "before_reconfine" and not swapped:
            journals.rename(retained)
            journals.symlink_to(outside, target_is_directory=True)
            swapped = True

    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))
    try:
        assert execute_transition(plan, fault=swap).success
        assert list(outside.iterdir()) == []
        assert list(retained.iterdir()) == []
    finally:
        if journals.is_symlink():
            journals.unlink()
        if retained.exists():
            retained.rename(journals)


def test_same_worktree_transitions_are_serialized_by_nofollow_exclusive_lock(repo: Path) -> None:
    ready = repo.parent / f"{repo.name}-lock-ready"
    first_script = r"""
import sys, time
from pathlib import Path
from aviato.core.transition import TransitionChange, build_transition_plan, execute_transition
root, ready = Path(sys.argv[1]), Path(sys.argv[2])
plan = build_transition_plan(root, snapshot_sha="a" * 40, declaration_identity="id",
    changes=(TransitionChange.write("first.txt", b"one\n", category="managed"),), allow_dirty=True)
def fault(phase, operation):
    if phase == "prepared_fsync":
        ready.write_text("ready")
        time.sleep(30)
execute_transition(plan, fault=fault)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", first_script, str(repo), str(ready)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(200):
            if ready.exists():
                break
            if child.poll() is not None:
                break
            time.sleep(0.01)
        assert ready.exists(), child.communicate(timeout=1)

        second_script = r"""
import sys
from pathlib import Path
from aviato.core.transition import (TransitionChange, TransitionRecoveryError,
    build_transition_plan, execute_transition)
root = Path(sys.argv[1])
plan = build_transition_plan(root, snapshot_sha="a" * 40, declaration_identity="id",
    changes=(TransitionChange.write("second.txt", b"two\n", category="managed"),), allow_dirty=True)
try:
    execute_transition(plan)
except TransitionRecoveryError as exc:
    print(exc)
    raise SystemExit(17)
raise SystemExit(0)
"""
        second = subprocess.run(
            [sys.executable, "-c", second_script, str(repo)],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert second.returncode == 17
        assert "locked" in second.stdout
        assert not (repo / "second.txt").exists()
    finally:
        child.kill()
        child.wait(timeout=5)
        ready.unlink(missing_ok=True)
    inspection = inspect_transition(repo)
    assert inspection.pending
    rollback_transition(repo, inspection.journal_id)


def test_torn_unlocked_lock_metadata_is_replaceable_without_a_pending_journal(repo: Path) -> None:
    with transition_module._transition_lock(repo, recovery=False):
        pass
    state, _git_dir, _namespace = transition_module._state_paths(repo)
    (state / "execution.lock").write_bytes(b'{"sch')
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))

    assert execute_transition(plan).success


def test_torn_lock_with_pending_journal_requires_but_allows_explicit_recovery(repo: Path) -> None:
    plan = _plan(repo, TransitionChange.write("managed.txt", b"desired\n", category="managed"))
    with pytest.raises(KeyboardInterrupt):
        execute_transition(
            plan,
            fault=lambda phase, _operation: (
                (_ for _ in ()).throw(KeyboardInterrupt) if phase == "prepared_fsync" else None
            ),
        )
    inspection = inspect_transition(repo)
    state, _git_dir, _namespace = transition_module._state_paths(repo)
    (state / "execution.lock").write_bytes(b'{"sch')
    different = _plan(repo, TransitionChange.write("other.txt", b"other\n", category="managed"))

    with pytest.raises(TransitionRecoveryError, match="explicit recovery"):
        execute_transition(different)

    rollback_transition(repo, inspection.journal_id)
    assert not inspect_transition(repo).pending


@pytest.mark.parametrize(
    "kill_phase",
    [
        "journal_dir_fsync",
        "manifest_fsync",
        "preimage_created",
        "preimage_fsync",
        "backup_dir_fsync",
        "prepared_fsync",
        "temp_created",
        "temp_fsync",
        "before_mutation_syscall",
        "mutation",
        "target_dir_fsync",
        "applied_fsync",
        "final_diagnosis",
        "accepted_fsync",
        "journal_terminal_fsync",
        "journal_parent_fsync",
    ],
)
def test_sigkill_at_every_wal_phase_is_recoverable_or_honestly_conflicted(repo: Path, kill_phase: str) -> None:
    # Real process death proves recovery does not depend on Python exception cleanup.
    target = repo / "managed.txt"
    target.write_bytes(b"before\n")
    _commit_fixture(repo)
    script = r"""
import os, signal, sys
from pathlib import Path
from aviato.core.transition import TransitionChange, build_transition_plan, execute_transition
root = Path(sys.argv[1])
phase_to_kill = sys.argv[2]
plan = build_transition_plan(root, snapshot_sha="a" * 40, declaration_identity="id",
    changes=(TransitionChange.write("managed.txt", b"after\n", category="managed"),), allow_dirty=True)
def fault(phase, operation):
    if phase == phase_to_kill:
        os.kill(os.getpid(), signal.SIGKILL)
execute_transition(plan, fault=fault)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(repo), kill_phase],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == -signal.SIGKILL
    inspection = inspect_transition(repo)
    if inspection.pending:
        if inspection.operations and all(
            operation.status is OperationStatus.COMPLETED for operation in inspection.operations
        ):
            resume_pending_transition(repo, inspection.journal_id)
            assert target.read_bytes() == b"after\n"
        else:
            rollback_transition(repo, inspection.journal_id)
            assert target.read_bytes() == b"before\n"
    else:
        # Once the accepted journal has been atomically renamed to a terminal
        # name, the transition is durably committed even if garbage collection
        # of its private state is interrupted.
        assert kill_phase in {"journal_terminal_fsync", "journal_parent_fsync"}
        assert target.read_bytes() == b"after\n"
        follow_up = _plan(repo, TransitionChange.write("next.txt", b"next\n", category="managed"))
        assert execute_transition(follow_up).success


def test_parent_directory_swap_cannot_redirect_write_or_delete_outside_root(repo: Path) -> None:
    parent = repo / "managed"
    outside = repo.parent / f"{repo.name}-outside"
    parent.mkdir()
    outside.mkdir()
    (parent / "write.txt").write_bytes(b"inside\n")
    (parent / "delete.txt").write_bytes(b"inside\n")
    (outside / "write.txt").write_bytes(b"outside\n")
    (outside / "delete.txt").write_bytes(b"outside\n")
    _commit_fixture(repo)
    plan = _plan(
        repo,
        TransitionChange.write("managed/write.txt", b"desired\n", category="managed"),
        TransitionChange.delete("managed/delete.txt", category="managed"),
    )
    moved = repo / "managed-original"

    def swap(phase: str, operation: object) -> None:
        if phase == "before_mutation_syscall" and getattr(operation, "path", None) == "managed/write.txt":
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises((TransitionConflictError, TransitionExecutionError)):
        execute_transition(plan, fault=swap)

    assert (outside / "write.txt").read_bytes() == b"outside\n"
    assert (outside / "delete.txt").read_bytes() == b"outside\n"


def test_parent_swap_inside_replace_syscall_is_compensated_before_failure(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = repo / "managed"
    outside = repo.parent / f"{repo.name}-outside-syscall"
    moved = repo / "managed-moved"
    parent.mkdir()
    outside.mkdir()
    (parent / "write.txt").write_bytes(b"inside\n")
    (outside / "write.txt").write_bytes(b"outside\n")
    _commit_fixture(repo)
    plan = _plan(repo, TransitionChange.write("managed/write.txt", b"desired\n", category="managed"))
    real_replace = os.replace
    swapped = False

    def racing_replace(
        src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        dst: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if (
            not swapped
            and dst == "write.txt"
            and isinstance(src, str)
            and src.startswith(".aviato-transition-")
            and "compensate" not in src
        ):
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        real_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "replace", racing_replace)
    with pytest.raises(TransitionExecutionError, match="explicit recovery"):
        execute_transition(plan)

    assert (outside / "write.txt").read_bytes() == b"outside\n"
    assert (moved / "write.txt").read_bytes() == b"inside\n"
    parent.unlink()
    moved.rename(parent)
    pending = inspect_transition(repo)
    rollback_transition(repo, pending.journal_id)
