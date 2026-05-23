from __future__ import annotations

from dataclasses import dataclass

# Normalized authorization vocabulary (review #16). The hosting-platform binding maps the
# platform's OWN actor-type / permission-role strings (GitHub: "User" / "admin") to these neutral
# values BEFORE they cross the Platform port into core (§2.14) — so this gate, the most
# security-critical core code, carries no platform vocabulary. A different platform (e.g. GitLab,
# whose access levels are numeric) is supported by mapping in its binding, never by editing core.
ACTOR_HUMAN = "human"
ROLE_PRIVILEGED = "privileged"


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
    human (``actor_type == ACTOR_HUMAN``; unknown → deny), consent is bound to the
    **current** diff (§6.4; stale → deny), the role lookup succeeded (a failure
    is not approval), and the role is privileged (``role == ROLE_PRIVILEGED``).
    ``actor_type``/``role`` are the NORMALIZED values the binding mapped from the
    platform's own vocabulary (review #16) — core never sees "User"/"admin".
    """
    if actor_type != ACTOR_HUMAN:
        return Decision(False, f"actor is not a real human (type={actor_type!r})")
    if not consent_diff_id or not current_diff_id:
        # An empty/None binding is not consent — never let two falsy ids compare equal
        # and slip through the stale check (§5.8 fail-closed).
        return Decision(False, "no diff-bound consent present")
    if consent_diff_id != current_diff_id:
        return Decision(False, "consent is stale: bound diff does not match the current diff")
    if not role_lookup_ok:
        return Decision(False, "role lookup failed; lookup failure is not approval")
    if role != ROLE_PRIVILEGED:
        return Decision(False, f"role {role!r} is not authorized (privileged role required)")
    return Decision(True, "human consent bound to current diff, privileged role")
