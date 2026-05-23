from __future__ import annotations

from aviato.core.provision import minimal_settings, provision_repo

from .fakeplatform import FakePlatform

DESIRED = {
    "requires_pull_request": True,
    "required_reviews": 1,
    "block_force_push": True,
    "block_deletion": True,
    "required_status_checks": ["ci / Python CI"],
    "secret_scanning": True,
    "secret_push_protection": True,
    "dependency_scanning": True,
}


def test_minimal_settings_block_destructive_but_no_pr_gate() -> None:
    # §2.11/§8.7: minimal protection must not require a PR (it would deadlock the first
    # direct push), but must still block force-push/deletion. Required reviews/status
    # checks and §17 security-prerequisite toggles are excluded (they arrive with full).
    m = minimal_settings()
    assert m["requires_pull_request"] is False
    assert m["block_force_push"] is True
    assert m["block_deletion"] is True
    assert "required_status_checks" not in m
    assert "required_reviews" not in m
    assert "secret_scanning" not in m


def test_provision_happy_path_orders_create_minimal_scaffold_full() -> None:
    platform = FakePlatform()
    order: list[str] = []

    def scaffold_push() -> None:
        order.append("scaffold")

    outcome = provision_repo(platform, repo="o/new", desired=DESIRED, private=True, scaffold_push=scaffold_push)
    assert outcome.ok
    names = platform.call_names()
    # create_repo, then minimal apply, then scaffold, then full apply — in that order.
    assert names[0] == "create_repo"
    assert names.count("apply_settings") == 2
    assert order == ["scaffold"]
    # the first apply is minimal (no PR gate), the second is the full desired set.
    first_apply = next(args for name, args in platform.calls if name == "apply_settings")
    assert first_apply[1]["requires_pull_request"] is False


def test_provision_reports_partial_state_when_full_protection_fails() -> None:
    # §8.7: a full-protection failure after the first commit must surface the
    # partially-provisioned state for the complete-protection recovery, never crash.
    platform = FakePlatform(fail_full_protection=True)
    outcome = provision_repo(platform, repo="o/new", desired=DESIRED, private=True, scaffold_push=lambda: None)
    assert outcome.partial is True
    assert outcome.full_applied is False
    assert outcome.created and outcome.minimal_applied and outcome.scaffolded
    assert "rejected" in outcome.reason


def test_provision_reports_exposed_state_when_minimal_protection_fails() -> None:
    # §8.7: if minimal protection fails AFTER the repo is created, the repo EXISTS and is
    # unprotected. provision_repo must NOT crash — it returns created=True, minimal_applied=False
    # so the caller can surface the exposed state + recovery, never leaving it silent.
    platform = FakePlatform(fail_apply=True)  # the FIRST apply (minimal) raises
    outcome = provision_repo(platform, repo="o/new", desired=DESIRED, private=True, scaffold_push=lambda: None)
    assert outcome.created is True
    assert outcome.minimal_applied is False
    assert outcome.scaffolded is False
    assert outcome.partial is True
    assert not outcome.ok


def test_provision_reports_partial_when_scaffold_push_fails() -> None:
    # §8.7: a scaffold-push failure after minimal protection leaves the repo protected (minimal)
    # but un-scaffolded — surfaced as partial, never crashing.
    platform = FakePlatform()

    def _boom() -> None:
        raise RuntimeError("push rejected")

    outcome = provision_repo(platform, repo="o/new", desired=DESIRED, private=True, scaffold_push=_boom)
    assert outcome.created and outcome.minimal_applied
    assert outcome.scaffolded is False
    assert outcome.partial is True
    assert "push rejected" in outcome.reason
