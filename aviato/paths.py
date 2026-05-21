from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The agnostic core package directory.
CORE_DIR = REPO_ROOT / "aviato" / "core"

# The day-zero plug-in tree and its maintained denylist (§9b).
PLUGINS_DIR = REPO_ROOT / "aviato" / "plugins"
DENYLIST_FILE = PLUGINS_DIR / "denylist.txt"

# The §5.10 module-source tree: where profile/bundle/template data lives.
MODULE_SOURCE_ROOT = REPO_ROOT
PROFILES_DIR = REPO_ROOT / "profiles"
BUNDLES_DIR = REPO_ROOT / "bundles"
