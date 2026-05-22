from __future__ import annotations

import pytest

from aviato.core.errors import CompositionError
from aviato.core.file_drift_flow import run_file_drift

from .fakeplatform import FakePlatform


def test_proposable_status_without_expected_body_raises_cleanly() -> None:
    # A proposable artifact (mergeable-drift/missing) absent from expected_bodies must
    # raise a classified CompositionError, not an opaque KeyError that crashes a fleet
    # scan / scheduled drift run mid-flight.
    with pytest.raises(CompositionError):
        run_file_drift(
            FakePlatform(),
            repo="o/r",
            profile="p",
            statuses={"missing.cfg": "missing"},
            expected_bodies={},  # no body for the proposable artifact
        )


def test_mergeable_drift_opens_identity_keyed_proposal() -> None:
    platform = FakePlatform()
    outcome = run_file_drift(
        platform,
        repo="o/r",
        profile="python-library",
        statuses={"ruff.toml": "mergeable-drift", ".editorconfig": "clean"},
        expected_bodies={"ruff.toml": "line-length = 120\n", ".editorconfig": "x\n"},
    )
    assert outcome.proposed == ["ruff.toml"]
    assert "open_or_update_proposal" in platform.call_names()
    _, args = next(c for c in platform.calls if c[0] == "open_or_update_proposal")
    branch, files = args[1], args[3]
    assert branch.startswith("aviato/sync/python-library-")
    assert "ruff.toml" in files


def test_missing_file_is_proposed() -> None:
    platform = FakePlatform()
    outcome = run_file_drift(
        platform,
        repo="o/r",
        profile="p",
        statuses={"mypy.ini": "missing"},
        expected_bodies={"mypy.ini": "[mypy]\n"},
    )
    assert "mypy.ini" in outcome.proposed


def test_dirty_drift_is_reported_not_proposed() -> None:
    platform = FakePlatform()
    outcome = run_file_drift(
        platform,
        repo="o/r",
        profile="p",
        statuses={"cfg.py": "dirty-drift"},
        expected_bodies={"cfg.py": "x\n"},
    )
    assert outcome.dirty == ["cfg.py"]
    assert outcome.proposed == []
    assert "open_or_update_proposal" not in platform.call_names()


def test_all_clean_is_noop() -> None:
    platform = FakePlatform()
    outcome = run_file_drift(platform, repo="o/r", profile="p", statuses={"a": "clean"}, expected_bodies={"a": "x\n"})
    assert outcome.proposed == []
    assert platform.calls == []


def test_bootstrap_skips_entirely() -> None:
    platform = FakePlatform()
    outcome = run_file_drift(
        platform,
        repo="o/r",
        profile="p",
        statuses={"a": "mergeable-drift"},
        expected_bodies={"a": "x\n"},
        is_bootstrap=True,
    )
    assert outcome.skipped is True
    assert platform.calls == []
