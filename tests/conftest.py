from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from aviato.paths import REPO_ROOT


@pytest.fixture
def task3_pinned_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit reusable fetched-snapshot double for pre-context CLI behavior tests."""

    from aviato import cli
    from aviato.core.registry import Registry

    snapshot_root = tmp_path.parent / f"{tmp_path.name}-library-snapshot"
    shutil.copytree(Path("aviato/library"), snapshot_root)
    snapshot = SimpleNamespace(registry=Registry(snapshot_root), policy_root=snapshot_root)
    monkeypatch.setattr(cli, "_open_consumer_context", lambda _root, _declaration: snapshot)
    monkeypatch.setattr(cli, "_open_new_context", lambda _root, _pin: snapshot)
    monkeypatch.setattr(cli, "_open_published_snapshot", lambda _pin: snapshot)
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run if the temp root resolves inside the repo (fail fast, fail loud).

    Python's ``tempfile`` falls back to the CURRENT WORKING DIRECTORY when ``$TMPDIR``
    and ``/tmp`` are unwritable (e.g. inside a filesystem sandbox). Several tests copy
    the whole repo into ``tmp_path``; with the temp root inside the repo, the copy
    destination lives inside the copy source and the run explodes into a recursive,
    multi-gigabyte tree. Catch that misconfiguration here, before any test runs.
    """
    temp_root = Path(tempfile.gettempdir()).resolve()
    repo_root = REPO_ROOT.resolve()
    if temp_root == repo_root or repo_root in temp_root.parents:
        raise RuntimeError(
            f"pytest temp root {temp_root} is inside the repository {repo_root}; "
            "tempfile fell back to the cwd (TMPDIR and /tmp are unwritable?). "
            "Set TMPDIR to a writable directory OUTSIDE the repo and re-run."
        )
