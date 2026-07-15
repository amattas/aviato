from __future__ import annotations

import copy
import importlib
import inspect
import json
from types import SimpleNamespace
from typing import Any

import pytest

from aviato.core.ports import RepositoryIdentity

SHA = "a" * 40


def _api() -> Any:
    return importlib.import_module("aviato.core.protection")


def _repo(**changes: Any) -> RepositoryIdentity:
    return RepositoryIdentity(
        database_id=int(changes.get("database_id", 7)),
        node_id=str(changes.get("node_id", "R_7")),
        full_name=str(changes.get("full_name", "o/r")),
        default_branch=str(changes.get("default_branch", "main")),
    )


def _ruleset(name: str = "Protect", *, approvals: int = 1, target: str = "branch") -> dict[str, Any]:
    return {
        "name": name,
        "target": target,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH" if target == "branch" else "~ALL"], "exclude": []}},
        "bypass_actors": [],
        "rules": [{"type": "pull_request", "parameters": {"required_approving_review_count": approvals}}],
    }


def _live_ruleset(payload: dict[str, Any], ruleset_id: int = 9) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result.update({"id": ruleset_id, "node_id": f"RRS_{ruleset_id}", "source_type": "Repository", "source": "o/r"})
    result["conditions"] = {
        "ref_name": {"include": ["refs/heads/main" if payload["target"] == "branch" else "refs/tags/*"], "exclude": []}
    }
    return result


def _desired() -> Any:
    return SimpleNamespace(
        settings={
            "default_branch": {"requires_pull_request": True, "required_reviews": 1},
            "repository": {"allow_squash_merge": True},
            "security": {"secret_scanning": True},
        },
        required_status_checks=("ci / Verify",),
        environments=("production",),
        authorization_guard=SimpleNamespace(path=".github/workflows/aviato-ci.yml", blob_sha="b" * 40, schema="v1"),
    )


def _environment() -> Any:
    api = _api()
    return api.ProtectedEnvironment(
        name="production",
        reviewers=(api.EnvironmentReviewer("user", "alice", 11, "U_11"),),
        minimum_approvals=1,
        prevent_self_review=True,
        branch_patterns=("main",),
        tag_patterns=("*.*.*",),
        wait_timer=0,
        custom_rules=(),
        forbid_admin_bypass=True,
    )


def _live(*, approvals: int = 0, admin_bypass: bool | None = False) -> dict[str, Any]:
    return {
        "repository_identity": _repo(),
        "classic": {"requires_pull_request": False, "required_reviews": approvals},
        "repository": {"allow_squash_merge": False},
        "security": {"secret_scanning": False},
        "merge": {"allow_squash_merge": False},
        "rulesets": [_live_ruleset(_ruleset(approvals=approvals))],
        "environments": {
            "production": {
                "reviewers": [{"type": "User", "id": 11, "node_id": "U_11", "login": "alice"}],
                "minimum_approvals": 1,
                "prevent_self_review": True,
                "branch_patterns": ["main"],
                "tag_patterns": ["*.*.*"],
                "wait_timer": 0,
                "custom_rules": [],
                "can_admins_bypass": admin_bypass,
            }
        },
        "checks": {"ci / Verify": "success"},
        "guard": {"path": ".github/workflows/aviato-ci.yml", "blob_sha": "b" * 40, "schema": "v1"},
        "release_guard": {
            "repository": "amattas/aviato",
            "ref": "1.0.0",
            "path": ".github/workflows/reusable-release.yml",
            "blob_sha": "c" * 40,
        },
        "verifier_guard": {
            "repository": "amattas/aviato",
            "ref": "1.0.0",
            "path": "aviato/authority_verifier.py",
            "blob_sha": "d" * 40,
        },
    }


def _plan(*, live: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return _api().build_protection_plan(
        repository=_repo(),
        tool_version="1.0.0",
        declaration_pin="1.0.0",
        snapshot_sha=SHA,
        desired_state=_desired(),
        desired_rulesets=[_ruleset()],
        live_state=live or _live(),
        environments=(_environment(),),
        **kwargs,
    )


def _persistence_evidence(**changes: Any) -> Any:
    api = _api()
    values = {
        "envelope": b"signed-envelope",
        "issue_node_id": "I_1",
        "comment_node_id": "IC_1",
        "source_comment_node_id": "IC_1",
        "comment_database_id": 44,
        "author": "alice",
        "author_database_id": 11,
        "author_is_admin": True,
        "key_id": "key-1",
        "key_current": True,
        "created_at": "2026-07-14T00:00:00Z",
        "last_edited_at": None,
        "is_minimized": False,
    }
    values.update(changes)
    return api.ReceiptPersistenceEvidence(**values)


def test_protection_plan_contains_classic_security_merge_ruleset_environment_and_checks() -> None:
    kinds = {operation.kind for operation in _plan().operations}
    assert {"classic", "repository", "security", "merge", "ruleset", "environment", "checks"} <= kinds


def test_protection_plan_binds_same_pinned_desired_state_as_transition() -> None:
    plan = _plan()
    assert plan.declaration_pin == "1.0.0" and plan.snapshot_sha == SHA
    assert '"snapshot_sha":"' + SHA + '"' in plan.canonical_json


def test_complete_protection_defaults_to_dry_run_and_requires_exact_confirm() -> None:
    api = _api()
    plan = _plan()
    assert api.require_protection_confirmation(plan, apply=False, confirmation=None) is None
    with pytest.raises(ValueError, match="confirm"):
        api.require_protection_confirmation(plan, apply=True, confirmation=None)


def test_complete_protection_applies_every_surface_not_settings_only() -> None:
    plan = _plan()
    assert sum(op.kind != "settings" for op in plan.operations) == len(plan.operations)


def test_provision_is_not_full_when_rulesets_fail_after_settings_succeed() -> None:
    api = _api()
    plan = _plan()
    writes: list[str] = []
    state = plan

    def write(op: Any) -> None:
        nonlocal state
        if op.kind == "ruleset":
            raise RuntimeError("ruleset rejected")
        writes.append(op.kind)
        state = api.plan_with_operation_converged(state, op.identity)

    result = api.execute_protection_plan(plan, confirmation=plan.plan_id, recompute=lambda: state, write=write)
    assert result.receipt.ready is False and result.receipt.status == "failed"


def test_known_tag_pattern_degradation_is_visible_and_non_ready() -> None:
    parameters = inspect.signature(_api().build_protection_plan).parameters
    assert "allow_degraded_tag_pattern" in parameters
    plan = _plan(allow_degraded_tag_pattern=True)
    tag_operation = next(
        operation for operation in plan.operations if operation.kind == "ruleset" and operation.name == "Protect"
    )
    assert tag_operation.degraded_desired is None


def test_full_noop_rerun_is_idempotent_only_after_fresh_binding() -> None:
    live = _live(approvals=1)
    live["classic"] = {"requires_pull_request": True, "required_reviews": 1}
    live["repository"] = {}
    live["security"] = {"secret_scanning": True}
    live["merge"] = {"allow_squash_merge": True}
    plan = _plan(live=live)
    assert all(op.action == "noop" for op in plan.operations)


def test_changed_repository_identity_default_branch_snapshot_or_live_state_refuses_apply() -> None:
    api = _api()
    plan = _plan()
    changed = _plan(live={**_live(), "repository_identity": _repo(default_branch="trunk")})
    with pytest.raises(ValueError, match="changed"):
        api.verify_protection_recheck(plan, changed, completed=frozenset())


def test_each_write_has_full_semantic_readback() -> None:
    api = _api()
    plan = _plan()
    reads = 0
    state = plan

    def recompute() -> Any:
        nonlocal reads
        reads += 1
        return state

    def write(op: Any) -> None:
        nonlocal state
        state = api.plan_with_operation_converged(state, op.identity)

    api.execute_protection_plan(plan, confirmation=plan.plan_id, recompute=recompute, write=write)
    assert reads >= 2 * sum(op.action != "noop" for op in plan.operations) + 1


def test_lost_response_is_completed_only_when_readback_proves_desired_state() -> None:
    api = _api()
    plan = _plan()
    state = plan

    def write(op: Any) -> None:
        nonlocal state
        state = api.plan_with_operation_converged(state, op.identity)
        raise api.ResponseLostError("lost")

    result = api.execute_protection_plan(plan, confirmation=plan.plan_id, recompute=lambda: state, write=write)
    assert result.receipt.status in {"ready", "failed"}


def test_unreadable_post_write_state_is_indeterminate_and_never_blindly_retried() -> None:
    api = _api()
    plan = _plan()
    calls = 0

    def write(_op: Any) -> None:
        nonlocal calls
        calls += 1
        raise api.ResponseLostError("lost")

    result = api.execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: (_ for _ in ()).throw(RuntimeError("unreadable")),
        write=write,
    )
    assert result.receipt.status == "indeterminate" and calls <= 1


def test_later_operations_are_unattempted_after_failure_or_indeterminate_result() -> None:
    api = _api()
    result = api.execute_protection_plan(
        _plan(),
        confirmation=_plan().plan_id,
        recompute=lambda: _plan(),
        write=lambda _op: (_ for _ in ()).throw(RuntimeError("stop")),
    )
    assert any(item.status == "unattempted" for item in result.receipt.operations[1:])


def test_unknown_environment_reviewer_identity_is_unattempted_and_non_ready() -> None:
    api = _api()
    env = api.ProtectedEnvironment("production", (), 1, True, (), (), 0, (), True)
    plan = api.build_protection_plan(
        repository=_repo(),
        tool_version="1",
        declaration_pin="1",
        snapshot_sha=SHA,
        desired_state=_desired(),
        desired_rulesets=[_ruleset()],
        live_state=_live(),
        environments=(env,),
    )
    assert not plan.ready and any("reviewer" in blocker for blocker in plan.blockers)


def test_final_convergence_barrier_catches_earlier_or_post_last_write_drift() -> None:
    api = _api()
    plan = _plan()
    result = api.execute_protection_plan(
        plan, confirmation=plan.plan_id, recompute=lambda: plan, write=lambda _op: None
    )
    assert result.receipt.ready is False


def test_degraded_tag_fallback_requires_bound_payload_and_explicit_consent() -> None:
    tag_rule = _ruleset(name="Release tags", target="tag")
    tag_rule["rules"].append({"type": "tag_name_pattern", "parameters": {"pattern": "1.*"}})
    plan = _api().build_protection_plan(
        repository=_repo(),
        tool_version="1.0.0",
        declaration_pin="1.0.0",
        snapshot_sha=SHA,
        desired_state=_desired(),
        desired_rulesets=[tag_rule],
        live_state={**_live(), "rulesets": []},
        environments=(_environment(),),
        allow_degraded_tag_pattern=True,
    )
    operation = next(item for item in plan.operations if item.kind == "ruleset")
    assert operation.degraded_desired is not None
    assert operation.degraded_fingerprint
    assert json.loads(plan.canonical_json)["allow_degraded_tag_pattern"] is True
    assert operation.degraded_reason == "github-unsupported-tag_name_pattern-422"


def test_protection_receipt_is_attached_with_ruleset_ids_and_payload_fingerprints() -> None:
    receipt = _api().receipt_for_plan(_plan(), status="ready")
    assert receipt.plan_id and receipt.rulesets[0]["id"] == 9 and receipt.rulesets[0]["fingerprint"]


def test_receipt_comment_failure_preserves_local_truth_and_blocks_auto_retirement() -> None:
    receipt = _api().receipt_for_plan(_plan(), status="ready", persistence_status="failed")
    assert receipt.local_mutations_recorded and not receipt.auto_retirement_authorized


def test_explicit_environment_reviewers_and_ref_policy_apply_and_read_back() -> None:
    plan = _plan()
    env = next(op for op in plan.operations if op.kind == "environment")
    assert env.desired["reviewers"][0]["id"] == 11 and env.desired["branch_patterns"] == ["main"]


def test_environment_api_fields_wait_and_custom_rules_are_plan_bound() -> None:
    assert "wait_timer" in _plan().canonical_json and "custom_rules" in _plan().canonical_json


def test_read_only_environment_admin_bypass_requires_false_or_manual_blocker() -> None:
    assert _plan(live=_live(admin_bypass=None)).ready is False


def test_admin_bypass_false_and_independent_authorization_guard_are_both_required() -> None:
    plan = _plan()
    assert plan.ready and plan.authorization_guard and '"can_admins_bypass":false' in plan.canonical_json


def test_ruleset_operation_preserves_confirmed_immutable_identity_and_writes_fresh_recheck() -> None:
    api = _api()
    plan = _plan()
    rule = next(operation for operation in plan.operations if operation.kind == "ruleset")
    assert rule.ruleset_identity == plan.ruleset_plan.operations[0].identity

    fresh_plan = _plan()
    fresh_rule = next(operation for operation in fresh_plan.operations if operation.kind == "ruleset")
    written: list[Any] = []
    state = fresh_plan

    def recompute() -> Any:
        return state

    def write(operation: Any) -> None:
        nonlocal state
        written.append(operation)
        state = api.plan_with_operation_converged(state, operation.identity)

    api.execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=recompute,
        write=write,
        persist_receipt=lambda _receipt: _persistence_evidence(),
    )
    assert any(item is fresh_rule for item in written)


def test_ruleset_replacement_between_confirmation_and_write_is_rejected() -> None:
    plan = _plan()
    live = _live()
    live["rulesets"] = [_live_ruleset(_ruleset(), ruleset_id=77)]
    replaced = _plan(live=live)
    writes: list[Any] = []
    result = _api().execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: replaced,
        write=writes.append,
        persist_receipt=lambda _receipt: _persistence_evidence(),
    )
    assert result.receipt.status == "indeterminate" and writes == []


def test_unsupported_custom_environment_rule_drift_blocks_before_any_write() -> None:
    live = _live()
    live["environments"]["production"]["custom_rules"] = [{"type": "custom", "id": 3}]
    plan = _plan(live=live)
    writes: list[Any] = []
    result = _api().execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: plan,
        write=writes.append,
        persist_receipt=lambda _receipt: _persistence_evidence(),
    )
    assert not plan.ready and writes == [] and result.receipt.status == "blocked"


def test_ready_receipt_is_built_from_final_readback_and_requires_durable_persistence() -> None:
    api = _api()
    plan = _plan()
    state = plan
    persisted: list[bytes] = []

    def write(operation: Any) -> None:
        nonlocal state
        state = api.plan_with_operation_converged(state, operation.identity)

    result = api.execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: state,
        write=write,
        persist_receipt=lambda canonical: (persisted.append(canonical), _persistence_evidence())[1],
    )
    assert result.receipt.ready
    assert result.receipt.final_fingerprint == api.protection_state_fingerprint(state)
    assert result.receipt.repository == _repo()
    assert persisted == [result.receipt.canonical_bytes]

    state = plan
    without_persistence = api.execute_protection_plan(
        plan, confirmation=plan.plan_id, recompute=lambda: state, write=write
    )
    assert not without_persistence.receipt.ready


def test_receipt_preserves_confirmed_plan_id_separately_from_final_live_plan_id() -> None:
    api = _api()
    confirmed = _plan()
    final_live = _live()
    final_live["classic"] = {"requires_pull_request": True, "required_reviews": 1}
    final = _plan(live=final_live)
    receipt = api.receipt_for_plan(final, confirmed_plan=confirmed, status="ready", persistence_status="attached")
    assert receipt.confirmed_plan_id == confirmed.plan_id
    assert receipt.final_plan_id == final.plan_id
    assert receipt.confirmed_plan_id != receipt.final_plan_id


def test_final_receipt_carries_one_versioned_canonical_live_authority_snapshot() -> None:
    api = _api()
    live = _live(approvals=1)
    live.update(
        classic={"requires_pull_request": True, "required_reviews": 1},
        repository={},
        security={"secret_scanning": True},
        merge={"allow_squash_merge": True},
        required_checks=[{"context": "ci / Verify", "app_id": 7, "integration_id": None, "source": "classic"}],
        release_guard={
            "repository": "amattas/aviato",
            "ref": "1.0.0",
            "path": ".github/workflows/reusable-release.yml",
            "blob_sha": "c" * 40,
        },
    )
    receipt = api.receipt_for_plan(_plan(live=live), status="ready", persistence_status="attached")

    snapshot = receipt.authority_snapshot
    assert snapshot["schema"] == "aviato-protection-authority-snapshot/v1"
    assert snapshot["repository"] == {
        "database_id": 7,
        "node_id": "R_7",
        "full_name": "o/r",
        "default_branch": "main",
    }
    assert snapshot["rulesets"][0]["id"] == 9
    assert snapshot["required_checks"] == live["required_checks"]
    assert snapshot["guard"]["intake"]["blob_sha"] == "b" * 40
    assert snapshot["guard"]["release"]["blob_sha"] == "c" * 40
    assert receipt.final_fingerprint == api.authority_snapshot_digest(snapshot)


def test_release_guard_blob_drift_changes_final_live_authority_fingerprint() -> None:
    api = _api()
    first_live = _live(approvals=1)
    first_live.update(
        classic={"requires_pull_request": True, "required_reviews": 1},
        repository={},
        security={"secret_scanning": True},
        merge={"allow_squash_merge": True},
        release_guard={
            "repository": "amattas/aviato",
            "ref": "1.0.0",
            "path": ".github/workflows/reusable-release.yml",
            "blob_sha": "c" * 40,
        },
    )
    second_live = copy.deepcopy(first_live)
    second_live["release_guard"]["blob_sha"] = "d" * 40

    assert api.protection_state_fingerprint(_plan(live=first_live)) != api.protection_state_fingerprint(
        _plan(live=second_live)
    )


def test_signed_receipt_evidence_requires_immutable_unedited_current_admin_metadata() -> None:
    api = _api()
    evidence = _persistence_evidence()
    assert api.receipt_persistence_ready(evidence)
    assert not api.receipt_persistence_ready(api.replace(evidence, last_edited_at="2026-07-14T00:01:00Z"))
    assert not api.receipt_persistence_ready(api.replace(evidence, key_current=False))


def test_receipt_envelope_ssh_signs_and_verifies_exact_canonical_receipt_bytes() -> None:
    api = _api()
    receipt = api.receipt_for_plan(_plan(), status="ready", persistence_status="attached")
    seen: list[bytes] = []
    envelope = api.sign_protection_receipt(
        receipt.canonical_bytes,
        principal="alice",
        key_id="key-1",
        signer=lambda message: (seen.append(message), b"signature")[1],
    )
    verified = api.verify_protection_receipt_envelope(
        envelope,
        expected_receipt=receipt.canonical_bytes,
        expected_principal="alice",
        expected_key_id="key-1",
        verify_signature=lambda message, signature: message == receipt.canonical_bytes and signature == b"signature",
    )
    assert verified == receipt.canonical_bytes and seen == [receipt.canonical_bytes]
    with pytest.raises(ValueError):
        api.verify_protection_receipt_envelope(
            envelope,
            expected_receipt=receipt.canonical_bytes + b" ",
            expected_principal="alice",
            expected_key_id="key-1",
            verify_signature=lambda *_args: True,
        )


def test_ruleset_replacement_after_write_is_rejected_before_subsequent_write() -> None:
    api = _api()
    plan = _plan()
    state = plan
    writes: list[Any] = []

    def write(operation: Any) -> None:
        nonlocal state
        writes.append(operation)
        if operation.kind == "ruleset":
            live = _live()
            live["rulesets"] = [_live_ruleset(_ruleset(), ruleset_id=77)]
            # Keep all earlier completed non-ruleset surfaces converged while replacing
            # the exact ruleset identity after its write.
            state = _plan(live=live)
            for prior in plan.operations:
                if prior.kind != "ruleset" and prior.identity in {item.identity for item in writes}:
                    state = api.plan_with_operation_converged(state, prior.identity)
        else:
            state = api.plan_with_operation_converged(state, operation.identity)

    result = api.execute_protection_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: state,
        write=write,
        persist_receipt=lambda _canonical: _persistence_evidence(),
    )
    assert result.receipt.status == "indeterminate"
    ruleset_index = next(index for index, item in enumerate(writes) if item.kind == "ruleset")
    assert len(writes) == ruleset_index + 1
