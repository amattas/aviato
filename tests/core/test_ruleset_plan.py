from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

import pytest

from aviato.core.inventory import ManagedInventory, OwnedRulesetEntry
from aviato.core.ports import RepositoryIdentity

SNAPSHOT = "a" * 40
PRIOR_SNAPSHOT = "b" * 40


def _api() -> Any:
    return importlib.import_module("aviato.core.ruleset_plan")


def _repository(**changes: object) -> RepositoryIdentity:
    values: dict[str, object] = {
        "database_id": 17,
        "node_id": "R_repo_node",
        "full_name": "owner/repo",
        "default_branch": "main",
    }
    values.update(changes)
    return RepositoryIdentity(**values)  # type: ignore[arg-type]


def _desired(*, name: str = "Protect", target: str = "branch") -> dict[str, Any]:
    return {
        "name": name,
        "target": target,
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": ["~DEFAULT_BRANCH" if target == "branch" else "~ALL"],
                "exclude": [],
            }
        },
        "bypass_actors": [],
        "rules": [
            {
                "type": "pull_request",
                "parameters": {"required_approving_review_count": 2},
            },
            {"type": "non_fast_forward"},
        ],
    }


def _live(*, ruleset_id: int = 41, desired: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = copy.deepcopy(desired or _desired())
    payload["id"] = ruleset_id
    payload["conditions"] = {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}
    payload.update(
        {
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "html_url": "https://example.test/rules/41",
            "_links": {"self": {"href": "https://api.example.test/rules/41"}},
            "display": {"source_name": "owner/repo"},
        }
    )
    return payload


def _api_live(*, ruleset_id: int, desired: dict[str, Any]) -> dict[str, Any]:
    payload = _live(ruleset_id=ruleset_id, desired=desired)
    payload.update(
        {
            "node_id": f"RRS_{ruleset_id}",
            "source_type": "Repository",
            "source": "owner/repo",
        }
    )
    return payload


def _plan(
    *,
    desired: list[dict[str, Any]] | None = None,
    live: list[dict[str, Any]] | None = None,
    repository: RepositoryIdentity | None = None,
    pin: str = "1.2.3",
    snapshot: str = SNAPSHOT,
    **kwargs: object,
) -> Any:
    return _api().build_ruleset_plan(
        repository=repository or _repository(),
        tool_version="1.2.3",
        declaration_pin=pin,
        snapshot_sha=snapshot,
        desired_payloads=desired if desired is not None else [_desired()],
        live_payloads=live if live is not None else [_live()],
        **kwargs,
    )


def test_ruleset_plan_binds_repo_id_slug_default_branch_pin_snapshot_and_live_ids() -> None:
    plan = _plan()

    assert plan.repository == _repository()
    assert plan.declaration_pin == "1.2.3"
    assert plan.snapshot_sha == SNAPSHOT
    assert plan.operations[0].identity.live_id == 41
    canonical = plan.canonical_json
    assert '"database_id":17' in canonical
    assert '"node_id":"R_repo_node"' in canonical
    assert '"full_name":"owner/repo"' in canonical
    assert '"default_branch":"main"' in canonical
    assert '"declaration_pin":"1.2.3"' in canonical
    assert f'"snapshot_sha":"{SNAPSHOT}"' in canonical


def test_ruleset_plan_id_is_stable_and_ignores_only_display_metadata() -> None:
    baseline = _plan()
    metadata_only = _live()
    metadata_only.update(
        {
            "created_at": "2040-01-01T00:00:00Z",
            "updated_at": "2040-01-02T00:00:00Z",
            "html_url": "https://different.invalid/rules/41",
            "_links": {"self": {"href": "https://different.invalid/api/41"}},
            "display": {"source_name": "renamed display"},
        }
    )

    assert _plan(live=[metadata_only]).plan_id == baseline.plan_id
    changed_id = _live(ruleset_id=42)
    assert _plan(live=[changed_id]).plan_id != baseline.plan_id


def test_every_security_relevant_field_changes_the_plan_id() -> None:
    baseline = _plan().plan_id
    variants: list[tuple[str, dict[str, Any]]] = []
    for field, value in (
        ("enforcement", "evaluate"),
        ("bypass_actors", [{"actor_id": 9, "actor_type": "Team", "bypass_mode": "always"}]),
    ):
        changed = _desired()
        changed[field] = value
        variants.append((field, changed))
    changed_condition = _desired()
    changed_condition["conditions"]["ref_name"]["include"] = ["refs/heads/Main"]
    variants.append(("condition bytes and case", changed_condition))
    changed_rule = _desired()
    changed_rule["rules"][0]["parameters"]["required_approving_review_count"] = 3
    variants.append(("rule parameters", changed_rule))

    for field, changed in variants:
        assert _plan(desired=[changed]).plan_id != baseline, field


def test_duplicate_desired_or_live_name_target_identity_fails_closed() -> None:
    duplicate_desired = [_desired(), _desired()]
    duplicate_live = [_live(ruleset_id=1), _live(ruleset_id=2)]

    with pytest.raises(ValueError, match="duplicate desired"):
        _plan(desired=duplicate_desired)
    with pytest.raises(ValueError, match="duplicate live"):
        _plan(live=duplicate_live)


def test_plan_fetches_full_detail_for_every_paginated_ruleset_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from aviato import github
    from aviato.github_platform import GitHubPlatform

    summaries = [{"id": 11, "name": "one"}, {"id": 12, "name": "two"}]
    fetched: list[int] = []
    monkeypatch.setattr(github, "repository_rulesets", lambda _repo: summaries)

    def full(_repo: str, ruleset_id: int) -> dict[str, Any]:
        fetched.append(ruleset_id)
        return {"id": ruleset_id, "name": str(ruleset_id), "target": "branch", "rules": []}

    monkeypatch.setattr(github, "repository_ruleset", full)

    assert len(GitHubPlatform().read_rulesets("owner/repo")) == 2
    assert fetched == [11, 12]


def test_condition_sets_normalize_default_branch_and_target_appropriate_all() -> None:
    api = _api()
    branch = api.normalize_conditions(
        {"ref_name": {"include": ["~ALL", "~DEFAULT_BRANCH", "~ALL"], "exclude": ["Z", "a"]}},
        target="branch",
        default_branch="trunk",
    )
    tag = api.normalize_conditions(
        {"ref_name": {"include": ["~ALL"], "exclude": []}},
        target="tag",
        default_branch="trunk",
    )

    assert branch.value == {
        "ref_name": {
            "include": ("refs/heads/*", "refs/heads/trunk"),
            "exclude": ("Z", "a"),
        }
    }
    assert tag.value == {"ref_name": {"include": ("refs/tags/*",), "exclude": ()}}


@pytest.mark.parametrize(
    "conditions",
    [
        {"unknown": {}},
        {"ref_name": {"include": "~ALL", "exclude": []}},
        {"ref_name": {"include": ["~UNKNOWN"], "exclude": []}},
        {"ref_name": {"include": [b"refs/heads/main"], "exclude": []}},
    ],
)
def test_condition_bytes_case_unknown_keys_and_malformed_shapes_never_false_green(
    conditions: object,
) -> None:
    desired = _desired()
    desired["conditions"] = conditions

    plan = _plan(desired=[desired])

    assert plan.operations[0].comparison.state == "indeterminate"
    assert plan.applicable is False


def test_declaration_mode_derives_github_slug_and_rejects_mismatch_or_non_github_remote(tmp_path: Path) -> None:
    from aviato.cli import _derive_ruleset_declaration_slug

    assert _derive_ruleset_declaration_slug(tmp_path, "git@github.com:Owner/Repo.git", []) == "Owner/Repo"
    assert (
        _derive_ruleset_declaration_slug(tmp_path, "https://github.com/Owner/Repo.git", ["owner/repo"]) == "Owner/Repo"
    )
    with pytest.raises(ValueError, match="does not match"):
        _derive_ruleset_declaration_slug(tmp_path, "git@github.com:Owner/Repo.git", ["other/repo"])
    with pytest.raises(ValueError, match="GitHub"):
        _derive_ruleset_declaration_slug(tmp_path, "https://gitlab.com/Owner/Repo.git", [])


def test_apply_requires_exact_recomputed_confirmation_and_one_repository() -> None:
    api = _api()
    plan = _plan()

    assert api.require_apply_confirmation([plan], apply=False, confirmation=None) is None
    with pytest.raises(ValueError, match="exactly one repository"):
        api.require_apply_confirmation(
            [plan, _plan(repository=_repository(database_id=18, full_name="owner/two"))],
            apply=True,
            confirmation=plan.plan_id,
        )
    with pytest.raises(ValueError, match="--confirm"):
        api.require_apply_confirmation([plan], apply=True, confirmation=None)
    with pytest.raises(ValueError, match="does not match"):
        api.require_apply_confirmation([plan], apply=True, confirmation="0" * 64)
    assert api.require_apply_confirmation([plan], apply=True, confirmation=plan.plan_id) == plan


def test_apply_rejects_changed_repo_branch_pin_snapshot_ruleset_id_or_before_payload() -> None:
    api = _api()
    expected = _plan()
    changed_live = _live()
    changed_live["rules"][0]["parameters"]["required_approving_review_count"] = 1
    variants = [
        _plan(repository=_repository(database_id=18)),
        _plan(repository=_repository(default_branch="trunk")),
        _plan(pin="1.2.4"),
        _plan(snapshot="c" * 40),
        _plan(live=[_live(ruleset_id=42)]),
        _plan(live=[changed_live]),
    ]

    for recomputed in variants:
        with pytest.raises(ValueError, match="changed after preview"):
            api.verify_recomputed_plan(expected, recomputed)


def test_owned_ruleset_delete_requires_inventory_prior_render_live_match_and_receipt() -> None:
    api = _api()
    prior_payload = _desired(name="Retired")
    prior_fingerprint = api.ruleset_payload_fingerprint(
        prior_payload,
        target="branch",
        default_branch="main",
    )
    inventory = ManagedInventory(
        schema_version=1,
        profile="python-library",
        profile_identity="aviato-profile/python-library/v1",
        pin="1.0.0",
        snapshot_commit=PRIOR_SNAPSHOT,
        entries={},
        owned_rulesets=(OwnedRulesetEntry("Retired", "branch", PRIOR_SNAPSHOT, prior_fingerprint),),
    )
    receipt = {"signature": "task-11-test-receipt"}
    verified: list[Any] = []

    def verify(candidate: object, binding: object) -> bool:
        verified.append(binding)
        return candidate is receipt

    plan = _plan(
        desired=[],
        live=[_live(desired=prior_payload)],
        prior_inventory=inventory,
        prior_desired_payloads=[prior_payload],
        deletion_receipt=receipt,
        receipt_verifier=verify,
    )

    operation = plan.operations[0]
    assert operation.action == "delete"
    assert operation.disposition == "ready"
    assert verified and verified[0].plan_id == plan.plan_id
    assert verified[0].ruleset == operation.identity


def test_unsafe_ruleset_delete_is_reported_manual_without_mutation() -> None:
    api = _api()
    writes: list[str] = []
    plan = _plan(desired=[], live=[_live()])

    result = api.execute_ruleset_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: plan,
        upsert=lambda _operation: writes.append("upsert"),
        delete=lambda _operation: writes.append("delete"),
    )

    assert plan.operations[0].disposition == "manual"
    assert result.success is False
    assert result.operations[0].status == "unattempted"
    assert writes == []


def test_indeterminate_condition_comparison_cannot_apply() -> None:
    api = _api()
    desired = _desired()
    desired["conditions"] = {"ref_name": {"include": ["~UNKNOWN"], "exclude": []}}
    plan = _plan(desired=[desired])

    with pytest.raises(ValueError, match="indeterminate"):
        api.execute_ruleset_plan(
            plan,
            confirmation=plan.plan_id,
            recompute=lambda: plan,
            upsert=lambda _operation: pytest.fail("indeterminate plan must not write"),
            delete=lambda _operation: pytest.fail("indeterminate plan must not delete"),
        )


def test_two_sequential_writes_recheck_explicitly_evolving_live_state() -> None:
    api = _api()
    desired = [_desired(name="A"), _desired(name="B")]
    live = [_live(ruleset_id=41, desired=_desired(name="A")), _live(ruleset_id=42, desired=_desired(name="B"))]
    for payload in live:
        payload["rules"][0]["parameters"]["required_approving_review_count"] = 1
    mutable_live = copy.deepcopy(live)
    plan = _plan(desired=desired, live=mutable_live)
    rechecks: list[tuple[str, ...]] = []
    writes: list[str] = []

    def recompute() -> Any:
        rechecks.append(tuple(payload["name"] for payload in mutable_live))
        return _plan(desired=desired, live=mutable_live)

    def upsert(operation: Any) -> None:
        writes.append(operation.identity.name)
        for index, payload in enumerate(mutable_live):
            if payload["name"] == operation.identity.name:
                replacement = copy.deepcopy(desired[index])
                replacement["id"] = payload["id"]
                replacement["conditions"] = copy.deepcopy(payload["conditions"])
                mutable_live[index] = replacement
                break

    result = api.execute_ruleset_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=recompute,
        upsert=upsert,
        delete=lambda _operation: pytest.fail("no deletion expected"),
    )

    assert result.success is True
    assert writes == ["A", "B"]
    assert len(rechecks) == 2


def test_ready_delete_rechecks_receipt_authorization_and_uses_no_stale_operation() -> None:
    api = _api()
    prior_payload = _desired(name="Retired")
    fingerprint = api.ruleset_payload_fingerprint(prior_payload, target="branch", default_branch="main")
    inventory = ManagedInventory(
        schema_version=1,
        profile="python-library",
        profile_identity="aviato-profile/python-library/v1",
        pin="1.0.0",
        snapshot_commit=PRIOR_SNAPSHOT,
        entries={},
        owned_rulesets=(OwnedRulesetEntry("Retired", "branch", PRIOR_SNAPSHOT, fingerprint),),
    )
    authorized = True

    def verify(_candidate: object, _binding: object) -> bool:
        return authorized

    kwargs = {
        "desired": [],
        "live": [_live(desired=prior_payload)],
        "prior_inventory": inventory,
        "prior_desired_payloads": [prior_payload],
        "deletion_receipt": {"receipt": 1},
        "receipt_verifier": verify,
    }
    plan = _plan(**kwargs)
    authorized = False
    deletes: list[str] = []

    with pytest.raises(ValueError, match="authorization|applicable|changed"):
        api.execute_ruleset_plan(
            plan,
            confirmation=plan.plan_id,
            recompute=lambda: _plan(**kwargs),
            upsert=lambda _operation: pytest.fail("no upsert expected"),
            delete=lambda operation: deletes.append(operation.identity.name),
        )
    assert deletes == []


def test_future_top_level_security_state_is_bound_or_indeterminate() -> None:
    baseline = _plan()
    changed = _live()
    changed["future_security_mode"] = {"level": "strict"}
    changed_plan = _plan(live=[changed])

    assert changed_plan.plan_id != baseline.plan_id
    assert changed_plan.operations[0].comparison.state in {"changed", "indeterminate"}


def test_distinct_malformed_condition_state_never_collapses_to_one_plan_id() -> None:
    unknown_token = _desired()
    unknown_token["conditions"] = {"ref_name": {"include": ["~FUTURE"], "exclude": []}}
    malformed_shape = _desired()
    malformed_shape["conditions"] = {"ref_name": {"include": "~ALL", "exclude": []}}

    first = _plan(desired=[unknown_token])
    second = _plan(desired=[malformed_shape])

    assert first.operations[0].comparison.state == "indeterminate"
    assert second.operations[0].comparison.state == "indeterminate"
    assert first.plan_id != second.plan_id


def test_real_api_response_identity_metadata_converges_across_two_writes() -> None:
    api = _api()
    desired = [_desired(name="A"), _desired(name="B")]
    mutable_live = [
        _api_live(ruleset_id=41, desired=desired[0]),
        _api_live(ruleset_id=42, desired=desired[1]),
    ]
    for payload in mutable_live:
        payload["rules"][0]["parameters"]["required_approving_review_count"] = 1
    plan = _plan(desired=desired, live=mutable_live)
    writes: list[str] = []

    def upsert(operation: Any) -> None:
        writes.append(operation.identity.name)
        index = 0 if operation.identity.name == "A" else 1
        mutable_live[index] = _api_live(ruleset_id=41 + index, desired=desired[index])

    result = api.execute_ruleset_plan(
        plan,
        confirmation=plan.plan_id,
        recompute=lambda: _plan(desired=desired, live=mutable_live),
        upsert=upsert,
        delete=lambda _operation: pytest.fail("no deletion expected"),
    )

    assert result.success is True
    assert writes == ["A", "B"]
    converged = _plan(desired=desired, live=mutable_live)
    assert [operation.action for operation in converged.operations] == ["noop", "noop"]


@pytest.mark.parametrize(
    ("source_type", "source"),
    [("Organization", "owner"), ("Repository", "other/repo"), (None, "owner/repo")],
)
def test_non_repository_or_inconsistent_ruleset_source_fails_closed(
    source_type: str | None,
    source: str,
) -> None:
    live = _api_live(ruleset_id=41, desired=_desired())
    if source_type is None:
        live.pop("source_type")
    else:
        live["source_type"] = source_type
    live["source"] = source

    plan = _plan(live=[live])

    assert plan.operations[0].comparison.state == "indeterminate"
    assert plan.applicable is False


def test_order_distinct_unknown_security_arrays_have_distinct_plan_ids() -> None:
    first = _desired()
    first["future_ordered_steps"] = ["scan", "approve"]
    second = _desired()
    second["future_ordered_steps"] = ["approve", "scan"]

    first_plan = _plan(desired=[first])
    second_plan = _plan(desired=[second])

    assert first_plan.plan_id != second_plan.plan_id
