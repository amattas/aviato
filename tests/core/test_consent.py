from __future__ import annotations

from typing import cast

from aviato.core.consent import ACTOR_HUMAN, ROLE_PRIVILEGED, Decision, authorize


def _ok(
    *,
    actor_type: str | None = ACTOR_HUMAN,
    consent_diff_id: str | None = "abc",
    current_diff_id: str | None = "abc",
    role_lookup_ok: bool = True,
    role: str | None = ROLE_PRIVILEGED,
) -> Decision:
    # review #16: core's authorize sees the NEUTRAL vocabulary the binding maps platform values to.
    return authorize(
        actor_type=actor_type,
        consent_diff_id=consent_diff_id,
        current_diff_id=cast(str, current_diff_id),
        role_lookup_ok=role_lookup_ok,
        role=role,
    )


def test_allow_only_when_human_consent_current_and_admin() -> None:
    assert _ok().allowed is True


def test_non_human_actor_denied() -> None:
    assert _ok(actor_type="Bot").allowed is False


def test_unknown_actor_denied() -> None:
    assert _ok(actor_type=None).allowed is False


def test_stale_consent_denied() -> None:
    d = _ok(consent_diff_id="OLD", current_diff_id="NEW")
    assert d.allowed is False
    assert "consent" in d.reason.lower()


def test_role_lookup_failure_denied() -> None:
    assert _ok(role_lookup_ok=False, role=None).allowed is False


def test_non_admin_denied() -> None:
    assert _ok(role="write").allowed is False


def test_empty_or_none_diff_ids_denied() -> None:
    # Defense-in-depth: a missing/empty consent binding must never authorize, even
    # though None == None and "" == "" would pass the equality check (§5.8 fail-closed).
    assert _ok(consent_diff_id=None, current_diff_id=None).allowed is False
    assert _ok(consent_diff_id="", current_diff_id="").allowed is False
