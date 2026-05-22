from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .filedrift import proposal_identity
from .ports import Platform

# Statuses (from §5.4 diagnosis) that a propose-only drift run may regenerate.
_PROPOSABLE = {"mergeable-drift", "missing"}


@dataclass
class FileDriftOutcome:
    proposed: list[str] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)
    branch: str | None = None
    skipped: bool = False


def _render_proposal_body(proposed: list[str]) -> str:
    lines = ["Aviato regenerated managed files that drifted from the pinned convention set.", "", "Files:"]
    lines += [f"- {output}: regenerated to match the resolved template (mergeable)" for output in proposed]
    lines += ["", "dirty-drift files (if any) are reported separately and never auto-changed (§5.5)."]
    return "\n".join(lines)


def run_file_drift(
    platform: Platform,
    *,
    repo: str,
    profile: str,
    statuses: Mapping[str, str],
    expected_bodies: Mapping[str, str],
    is_bootstrap: bool = False,
) -> FileDriftOutcome:
    """Propose (never force) regeneration of drifted managed files (§5.5).

    Skipped entirely in bootstrap. Mergeable-drift and missing artifacts are
    regenerated into an **identity-keyed** proposal (so a scheduled run and an
    operator ``scan --fix`` converge on the same branch, §8.11). dirty-drift is
    reported, never auto-changed.
    """
    if is_bootstrap:
        return FileDriftOutcome(skipped=True)

    proposed = sorted(o for o, status in statuses.items() if status in _PROPOSABLE)
    dirty = sorted(o for o, status in statuses.items() if status == "dirty-drift")

    outcome = FileDriftOutcome(proposed=proposed, dirty=dirty)
    if not proposed:
        return outcome

    branch = proposal_identity(profile, list(statuses))
    files = {output: expected_bodies[output] for output in proposed}
    platform.open_or_update_proposal(repo, branch, "Aviato: managed file sync", files, _render_proposal_body(proposed))
    outcome.branch = branch
    return outcome
