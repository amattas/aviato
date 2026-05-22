from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .marker import content_hash


def body_drift(*, expected_body: str, live_body: str) -> bool:
    """True iff the rendered body changed, ignoring the marker version and line endings (§5.5).

    Comparison hashes the body with line endings normalized; the marker's
    *version* field is excluded by construction (it is not part of ``body``), so
    a release/tag movement that changes nothing but the version is a no-op, never
    churn (§8.12).
    """
    return content_hash(expected_body) != content_hash(live_body)


def proposal_identity(profile: str, outputs: Sequence[str]) -> str:
    """A deterministic branch/PR key derived from profile + output set (§5.5).

    Order-independent (set semantics over outputs) so a scheduled drift job and
    an operator ``scan --fix`` converge on the same proposal instead of racing
    into duplicates (§8.11).
    """
    digest = hashlib.sha256("\n".join(sorted(set(outputs))).encode("utf-8")).hexdigest()[:12]
    return f"aviato/sync/{profile}-{digest}"
