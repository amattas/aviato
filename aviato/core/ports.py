from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Issue:
    """A tracking issue as seen by the core (§5.6/§5.7), free of platform specifics."""

    key: str
    open: bool
    consent_diff_id: str | None = None
    consent_actor_type: str | None = None
    consent_role: str | None = None
    consent_role_lookup_ok: bool = False
    edited_by_nonhuman_since_grant: bool = False
    # R2-5: more than one OPEN tracking issue shares this key — consent is ambiguous (a grant on
    # one duplicate, a revoke on another), so reconcile must refuse until they're de-duplicated.
    ambiguous: bool = False


@dataclass(frozen=True)
class RulesetApplyResult:
    """Outcome of one ruleset upsert, including any unsupported rules omitted."""

    message: str
    degraded_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingsApplyResult:
    """Outcome of one settings apply (§5.7), split into two operator-facing channels.

    ``skipped`` names desired toggles the binding surfaced-and-SKIPPED because the
    prerequisite feature was unavailable on the repo (the safety-critical branch
    protection still landed) — the §5.7 audit must report these so it does not
    overstate a clean apply. ``notes`` are free-text notes about extra mutations the
    apply performed OUTSIDE the reviewed diff (e.g. clearing a stale conflicting
    PR-review block a ruleset now owns).

    The two are SEPARATE channels precisely because a string cannot be classified
    after the fact: a skipped-toggle key and a mutation note are structurally
    distinct outcomes, and collapsing them into one list forces a lossy heuristic
    that mislabels one as the other in the audit trail. Field names are
    platform-neutral (§9b)."""

    skipped: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@runtime_checkable
class Platform(Protocol):
    """The §2.14 hosting-platform binding interface.

    The core depends only on this Protocol; the concrete GitHub binding lives
    outside the agnostic core (it is the day-zero binding). Read/propose/report
    methods are low-privilege; ``apply_settings`` is the only mutating call and is
    reached only through the §5.7 gated path.
    """

    def read_settings(self, repo: str) -> dict[str, Any]: ...

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]: ...

    def get_issue(self, repo: str, key: str) -> Issue | None: ...

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str: ...

    def comment_issue(self, repo: str, key: str, body: str) -> None: ...

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None: ...

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str: ...

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> SettingsApplyResult:
        """Apply the desired settings; return the skipped-toggle keys and any mutation notes.

        R5-4: a §17 security toggle (e.g. secret scanning) can be unavailable on the repo, in which
        case it is surfaced-and-skipped rather than failing the whole apply (the safety-critical
        branch protection still lands). Those keys come back in ``SettingsApplyResult.skipped`` so
        the §5.7 audit does not overstate a clean apply; extra mutations performed outside the diff
        come back in ``.notes``. An empty result means the full desired set applied with no extras.
        """
        ...

    def create_repo(self, repo: str, *, private: bool) -> None: ...
