from __future__ import annotations

import tempfile
from pathlib import Path

from aviato.paths import REPO_ROOT


def pytest_configure(config) -> None:
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
