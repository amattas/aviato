from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .ports import Platform
from .protection import ProtectionReceipt


def minimal_settings() -> dict[str, Any]:
    """The §2.11 safe-to-persist minimal protection: a fixed, profile-independent set.

    Blocks the destructive operations (force-push, deletion) but DOES NOT require a
    pull request — a PR-required gate would deadlock the very first direct push of the
    scaffold (§8.7). Required reviews / status checks arrive with full protection after
    the first commit. Repo security toggles are intentionally NOT applied here: they are
    §17 operator-prerequisite features that may be unavailable (e.g. secret scanning on
    a private repo without Advanced Security), so they belong to full protection, which
    enables them best-effort.

    This minimal set is the same regardless of the desired full protection (it is a
    safe floor, not a projection of ``desired``), so it takes no argument.
    """
    return {
        "requires_pull_request": False,
        "block_force_push": True,
        "block_deletion": True,
    }


@dataclass
class ProvisionOutcome:
    created: bool = False
    minimal_applied: bool = False
    scaffolded: bool = False
    full_applied: bool = False
    partial: bool = False  # full protection failed → repo is in the partially-provisioned state
    reason: str = ""
    # R2-1-PROV: §17 security toggles `apply_settings` surfaced-and-skipped because the feature is
    # unavailable on the repo. Full protection still landed, but the caller must report this rather
    # than claim a clean apply (mirrors the reconcile audit's "SKIPPED unavailable").
    skipped_security: list[str] = field(default_factory=list)
    protection_receipt: ProtectionReceipt | None = None

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
    authorize: Callable[[], None],
    full_protection: Callable[[], ProtectionReceipt] | None = None,
) -> ProvisionOutcome:
    """Provision-new staged protection order (§5.2/§2.11), operator-direct (§2.3).

    create repo → apply MINIMAL protection (safe to persist; does not block the first
    commit) → run ``scaffold_push`` (the local scaffold + first commit + push) → apply
    FULL protection. **Once the repo is created it EXISTS**, so every later stage is
    wrapped: any failure returns an outcome describing how far provisioning got (and a
    ``reason``), never crashing — so the caller can always surface the exposed/partial
    state and the recovery (§8.7). A new resource is never left unprotected with no
    recovery path, and full protection is never half-applied silently.

    ``scaffold_push`` performs the local git/scaffold side effects (kept out of core);
    platform calls go only through the :class:`Platform` port.
    """
    outcome = ProvisionOutcome()
    # create_repo is intentionally OUTSIDE the try: if it fails, nothing was created and the
    # caller's pre-create error path is correct. Everything after it operates on a repo that
    # now exists, so it must fail soft (§8.7).
    authorize()
    platform.create_repo(repo, private=private)
    outcome.created = True

    try:
        authorize()
        platform.apply_settings(repo, minimal_settings())
        outcome.minimal_applied = True
        authorize()
        scaffold_push()
        outcome.scaffolded = True
        # R2-1-PROV: the full-protection apply can surface-and-skip an unavailable §17 toggle;
        # capture it so the caller reports a partial apply instead of overstating clean success.
        # (The minimal apply carries no security keys, so its skipped set is always empty.)
        if full_protection is None:
            raise RuntimeError("full protection requires the confirmed composite executor and durable receipt")
        authorize()
        outcome.protection_receipt = full_protection()
        if not outcome.protection_receipt.ready or outcome.protection_receipt.persistence_status != "attached":
            raise RuntimeError(
                f"composite protection receipt is {outcome.protection_receipt.status}/"
                f"{outcome.protection_receipt.persistence_status}; repository is not fully protected"
            )
    except Exception as exc:  # noqa: BLE001 - §8.7 boundary: a post-create failure must surface
        # the exposed/partial state + recovery op, never crash or half-apply. The outcome flags
        # record exactly how far provisioning got (minimal_applied / scaffolded).
        outcome.partial = True
        outcome.reason = str(exc)
        return outcome

    outcome.full_applied = True
    return outcome
