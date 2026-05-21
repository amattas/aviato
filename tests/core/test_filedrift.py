from __future__ import annotations

from aviato.core.filedrift import body_drift, proposal_identity


def test_identical_body_is_not_drift() -> None:
    assert body_drift(expected_body="a\n", live_body="a\n") is False


def test_line_ending_only_change_is_not_drift() -> None:
    assert body_drift(expected_body="a\nb\n", live_body="a\r\nb\r\n") is False


def test_body_change_is_drift() -> None:
    assert body_drift(expected_body="a\n", live_body="b\n") is True


def test_proposal_identity_is_order_independent() -> None:
    a = proposal_identity("python-library", ["cfg.py", "ci.yml"])
    b = proposal_identity("python-library", ["ci.yml", "cfg.py"])
    assert a == b


def test_proposal_identity_is_stable_and_profile_scoped() -> None:
    a = proposal_identity("python-library", ["cfg.py"])
    assert a == proposal_identity("python-library", ["cfg.py"])
    assert a != proposal_identity("node-service", ["cfg.py"])
    assert a.startswith("aviato/sync/python-library-")
