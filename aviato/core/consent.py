from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def authorize(
    *,
    actor_type: str | None,
    consent_diff_id: str | None,
    current_diff_id: str,
    role_lookup_ok: bool,
    role: str | None,
) -> Decision:
    """The §5.8 fail-closed authorization gate, reused by every settings mutation.

    Defaults to DENY (§2.7). Allows only when **all** hold: the actor is a real
    human (``actor_type == "User"``; unknown → deny), consent is bound to the
    **current** diff (§6.4; stale → deny), the role lookup succeeded (a failure
    is not approval), and the role is ``admin``.
    """
    if actor_type != "User":
        return Decision(False, f"actor is not a real human (type={actor_type!r})")
    if consent_diff_id != current_diff_id:
        return Decision(False, "consent is stale: bound diff does not match the current diff")
    if not role_lookup_ok:
        return Decision(False, "role lookup failed; lookup failure is not approval")
    if role != "admin":
        return Decision(False, f"role {role!r} is not authorized (admin required)")
    return Decision(True, "human consent bound to current diff, admin role")
