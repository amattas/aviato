from __future__ import annotations

from aviato.core.consent import ACTOR_HUMAN, ROLE_PRIVILEGED, authorize


def _ok(**overrides):
    # review #16: core's authorize sees the NEUTRAL vocabulary the binding maps platform values to.
    base = dict(
        actor_type=ACTOR_HUMAN,
        consent_diff_id="abc",
        current_diff_id="abc",
        role_lookup_ok=True,
        role=ROLE_PRIVILEGED,
    )
    base.update(overrides)
    return authorize(**base)


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
