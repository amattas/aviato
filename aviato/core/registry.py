from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import CompositionError
from .model import (
    PipelineModule,
    Profile,
    ScaffoldBundle,
    SettingsBundle,
    TemplateModule,
    WorkflowsBundle,
)


def _load_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CompositionError(f"missing module definition: {path}")
    # R1-1: a malformed/unreadable module definition must raise CompositionError (an AviatoError),
    # not a raw yaml.YAMLError/OSError that escapes callers guarding only AviatoError.
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise CompositionError(f"module definition is not valid YAML: {path}: {exc}") from exc
    except OSError as exc:
        raise CompositionError(f"could not read module definition: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompositionError(f"module definition is not a mapping: {path}")
    return data


def _load_optional_manifest(path: Path) -> dict[str, Any]:
    """Read a manifest that may legitimately be absent, guarded like :func:`_load_doc` (R2-3-2).

    Absent → ``{}``. A malformed/unreadable manifest raises ``CompositionError`` (an AviatoError),
    never a raw ``yaml.YAMLError``/``OSError`` that would escape callers (e.g. ``scan_fleet``) which
    guard only AviatoError — the documented R1-1 invariant, previously not applied to the pipeline
    manifest loaders.
    """
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise CompositionError(f"manifest is not valid YAML: {path}: {exc}") from exc
    except OSError as exc:
        raise CompositionError(f"could not read manifest: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompositionError(f"manifest is not a mapping: {path}")
    return data


class Registry:
    """Loads profile/bundle/template module definitions from a source root.

    The source root is the §5.10 module-source tree: profile manifests at the
    root, ``bundles/<kind>/``, and ``scaffold/`` template modules. The registry
    maps the declarative YAML onto the :mod:`aviato.core.model` dataclasses. It
    contains no language- or deployment-specific knowledge — every such specific
    lives in the data it loads.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def profile_doc(self, name: str) -> dict[str, Any]:
        return _load_doc(self.root / f"{name}.yaml")

    def profile(self, name: str) -> Profile:
        doc = self.profile_doc(name)
        try:
            return Profile(
                name=doc["name"],
                workflows=doc["workflows"],
                scaffold=doc["scaffold"],
                settings=doc["settings"],
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

    def security_floor(self) -> dict[str, Any]:
        """The canonical always-on security baseline (§2.13, R1-4): the ``baseline`` settings
        bundle's ``security`` block. Composition enforces that NO profile/bundle/override composes
        a repo without it. Returns ``{}`` when there is no ``baseline`` bundle (a bare test
        registry), so the floor is enforced only where the Library actually declares one. The
        canonical floor lives in DATA (baseline.yaml), so core names no specific scanner (§9b)."""
        path = self.root / "bundles" / "settings" / "baseline.yaml"
        if not path.is_file():
            return {}
        return dict(self.settings_bundle("baseline").settings.get("security", {}))

    def pipeline_module(self, name: str) -> PipelineModule | None:
        """Load a typed pipeline module (§3.2/§11.3) from ``pipelines.yaml``.

        Returns None when the pipelines manifest is absent or the pipeline is not
        declared — composition tolerates this so test/empty registries still work;
        day-zero pipelines are all declared.
        """
        manifest = _load_optional_manifest(self.root / "pipelines.yaml")
        doc = manifest.get(name)
        if not isinstance(doc, dict):
            return None
        return PipelineModule(
            name=name,
            privileges=tuple(doc.get("privileges", ())),
            inputs=tuple(doc.get("inputs", ())),
            secrets=tuple(doc.get("secrets", ())),
            runner=doc.get("runner"),
            status_check=doc.get("status_check"),
            always_on=bool(doc.get("always_on", False)),
            environment=doc.get("environment"),
        )

    def always_on_pipelines(self) -> tuple[str, ...]:
        """Pipelines the data flags ``always_on`` — they must survive every composition (§2.13)."""
        manifest = _load_optional_manifest(self.root / "pipelines.yaml")
        return tuple(name for name, doc in manifest.items() if isinstance(doc, dict) and doc.get("always_on"))

    def declared_pipelines(self) -> set[str] | None:
        """The set of pipeline names the manifest declares, or None when no manifest exists (§5.1).

        Returns None — not an empty set — when ``pipelines.yaml`` is absent, so composition can
        distinguish "this registry declares pipelines, validate refs against them" from a bare
        test/empty registry that declares none (which stays lenient). The day-zero Library has a
        complete manifest, so an unknown pipeline ref there is a typo and must hard-error (§5.1).
        """
        path = self.root / "pipelines.yaml"
        if not path.is_file():
            return None  # absent → None (distinct from an empty manifest); see docstring
        return {name for name, doc in _load_optional_manifest(path).items() if isinstance(doc, dict)}

    def template_module(self, name: str) -> TemplateModule:
        doc = _load_doc(self.root / "scaffold" / f"{name}.yaml")
        return TemplateModule(
            output_path=doc["output_path"],
            source=doc["source"],
            seed_once=bool(doc.get("seed_once", False)),
            comment=doc.get("comment"),
            required_variables=tuple(doc.get("required_variables", ())),
            when=tuple(sorted((str(k), str(v)) for k, v in (doc.get("when") or {}).items())),
        )

    def template_body(self, module: TemplateModule) -> str:
        """Read a template module's raw source body from the module-source tree."""
        path = self.root / "scaffold" / module.source
        if not path.is_file():
            raise CompositionError(f"missing template source: {path}")
        return path.read_text(encoding="utf-8")
