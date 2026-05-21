from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The agnostic core package directory.
CORE_DIR = REPO_ROOT / "aviato" / "core"

# The day-zero plug-in tree and its maintained denylist (§9b).
PLUGINS_DIR = REPO_ROOT / "aviato" / "plugins"
DENYLIST_FILE = PLUGINS_DIR / "denylist.txt"

# The §5.10 module-source tree (profiles, bundles, scaffold templates). It lives
# INSIDE the package so it ships in the wheel and a pip-installed `aviato` (e.g.
# the consumer drift automation) can resolve profiles. Source checkouts resolve
# the same path.
MODULE_SOURCE_ROOT = Path(__file__).resolve().parent / "library"
BUNDLES_DIR = MODULE_SOURCE_ROOT / "bundles"
SCAFFOLD_DIR = MODULE_SOURCE_ROOT / "scaffold"
