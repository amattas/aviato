from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ports import Platform

# Repo-level security toggles are additive and safe to enable from the start; they
# do not block the first direct push the way a PR-required gate would.
_SAFE_SECURITY_KEYS = ("secret_scanning", "secret_push_protection", "dependency_scanning")


def minimal_settings(desired: dict[str, Any]) -> dict[str, Any]:
    """The §2.11 safe-to-persist minimal protection derived from the full desired set.

    Blocks the destructive operations (force-push, deletion) but DOES NOT require a
    pull request — a PR-required gate would deadlock the very first direct push of the
    scaffold (§8.7). Always-safe repo security toggles are carried forward immediately.
    Required reviews / status checks are intentionally omitted; they arrive with full
    protection after the first commit.
    """
    minimal: dict[str, Any] = {
        "requires_pull_request": False,
        "block_force_push": True,
        "block_deletion": True,
    }
    for key in _SAFE_SECURITY_KEYS:
        if key in desired:
            minimal[key] = desired[key]
    return minimal


@dataclass
class ProvisionOutcome:
    created: bool = False
    minimal_applied: bool = False
    scaffolded: bool = False
    full_applied: bool = False
    partial: bool = False  # full protection failed → repo is in the partially-provisioned state
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.full_applied and not self.partial


def provision_repo(
    platform: Platform,
    *,
    repo: str,
    desired: dict[str, Any],
    private: bool,
    scaffold_push: Callable[[], None],
) -> ProvisionOutcome:
    """Provision-new staged protection order (§5.2/§2.11), operator-direct (§2.3).

    create repo → apply MINIMAL protection (safe to persist; does not block the first
    commit) → run ``scaffold_push`` (the local scaffold + first commit + push) → apply
    FULL protection. If full protection fails after the first commit, the repo is left
    in the defined **partially-provisioned** state (minimal protection persists) and the
    outcome reports ``partial`` so the operator runs the idempotent ``complete-protection``
    recovery (§8.7) — full protection is never half-applied silently.

    ``scaffold_push`` performs the local git/scaffold side effects (kept out of core);
    platform calls go only through the :class:`Platform` port.
    """
    outcome = ProvisionOutcome()
    platform.create_repo(repo, private=private)
    outcome.created = True

    platform.apply_settings(repo, minimal_settings(desired))
    outcome.minimal_applied = True

    scaffold_push()
    outcome.scaffolded = True

    try:
        platform.apply_settings(repo, desired)
    except Exception as exc:  # noqa: BLE001 - §8.7 boundary: a full-protection failure must
        # surface the partially-provisioned state + recovery op, never crash or half-apply.
        outcome.partial = True
        outcome.reason = str(exc)
        return outcome

    outcome.full_applied = True
    return outcome
