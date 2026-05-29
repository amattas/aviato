from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_zizmor_is_pinned_exactly() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    # §11.3: tools are pinned to an EXACT version, never a floor/floating.
    assert "zizmor==" in text, "zizmor must be an exact-version (==) dependency of aviato"


def test_bundled_zizmor_config_encodes_the_pin_policy() -> None:
    cfg = yaml.safe_load((REPO / "aviato" / "library" / "zizmor.yml").read_text(encoding="utf-8"))
    policies = cfg["rules"]["unpinned-uses"]["config"]["policies"]
    assert policies["actions/*"] == "ref-pin"
    assert policies["github/*"] == "ref-pin"
    assert policies["amattas/aviato/*"] == "ref-pin"  # the one sanctioned mutable Library self-ref
    assert policies["*"] == "hash-pin"  # everything else SHA-required
