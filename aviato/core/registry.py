from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import CompositionError
from .model import (
    Profile,
    ScaffoldBundle,
    SettingsBundle,
    TemplateModule,
    WorkflowsBundle,
)


def _load_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CompositionError(f"missing module definition: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CompositionError(f"module definition is not a mapping: {path}")
    return data


class Registry:
    """Loads profile/bundle/template module definitions from a source root.

    The source root is the §5.10 module-source tree: ``profiles/``,
    ``bundles/<kind>/``, and ``templates/scaffold/``. The registry maps the
    declarative YAML onto the :mod:`aviato.core.model` dataclasses. It contains
    no language- or deployment-specific knowledge — every such specific lives in
    the data it loads.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def profile_doc(self, name: str) -> dict[str, Any]:
        return _load_doc(self.root / "profiles" / f"{name}.yaml")

    def profile(self, name: str) -> Profile:
        doc = self.profile_doc(name)
        try:
            return Profile(
                name=doc["name"],
                workflows=doc["workflows"],
                scaffold=doc["scaffold"],
                settings=doc["settings"],
                requires_macos=bool(doc.get("requires_macos", False)),
            )
        except KeyError as exc:
            raise CompositionError(f"profile {name!r} missing field: {exc}") from exc

    def workflows_bundle(self, name: str) -> WorkflowsBundle:
        doc = _load_doc(self.root / "bundles" / "workflows" / f"{name}.yaml")
        return WorkflowsBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            pipelines=tuple(doc.get("pipelines", ())),
            add=tuple(doc.get("add", ())),
            remove=tuple(doc.get("remove", ())),
        )

    def scaffold_bundle(self, name: str) -> ScaffoldBundle:
        doc = _load_doc(self.root / "bundles" / "scaffold" / f"{name}.yaml")
        return ScaffoldBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            templates=tuple(doc.get("templates", ())),
            add=tuple(doc.get("add", ())),
            remove=tuple(doc.get("remove", ())),
        )

    def settings_bundle(self, name: str) -> SettingsBundle:
        doc = _load_doc(self.root / "bundles" / "settings" / f"{name}.yaml")
        return SettingsBundle(
            name=doc["name"],
            extends=doc.get("extends"),
            settings=dict(doc.get("settings", {})),
        )

    def template_module(self, name: str) -> TemplateModule:
        doc = _load_doc(self.root / "templates" / "scaffold" / f"{name}.yaml")
        return TemplateModule(
            output_path=doc["output_path"],
            source=doc["source"],
            seed_once=bool(doc.get("seed_once", False)),
            comment=doc.get("comment"),
            required_variables=tuple(doc.get("required_variables", ())),
        )
