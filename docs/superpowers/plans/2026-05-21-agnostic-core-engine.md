# Aviato Agnostic Core Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agnostic core engine and plug-in module system described in `REQUIREMENTS.md` §3–§9, restructuring `aviato/` so language/deployment specifics live only as plug-in *data*, and the core's falsifiable agnosticism (§9) holds.

**Architecture:** A pure, deterministic core (`aviato/core/`) that knows how to *resolve* (§5.1), *scaffold* (§5.3), *diagnose* (§5.4), detect *drift* (§5.5/§5.6), *authorize* (§5.8), and check *compatibility*/*bootstrap* (§2.6/§5.10) — knowing nothing about any language or deploy target. Day-zero plug-ins are expressed as YAML data under `profiles/`, `bundles/`, `templates/` (the §5.10 module-source tree) and loaded by a registry. The core has **no import edge** into any plug-in tree and contains **none** of the §9 denylisted identifiers; a self-check (§9b) enforces both.

**Tech Stack:** Python ≥3.11, PyYAML, pytest, ruff. Dataclasses for the model. `hashlib` for content hashes. Atomic writes via `tempfile` + `os.replace`.

**Out-of-session scope (operator-side DoD):** §9 criteria 2–3/8 and §16.3 require *real* CI runs and *real* publishes (PyPI/GHCR/Pages/TestFlight). Those reusable workflows already exist in `.github/workflows/`. This plan wires plug-in pipeline declarations to them and unit-tests the engine; the live-platform runs remain operator-verified.

---

## File Structure

**New agnostic core package `aviato/core/`** (no language/deploy identifiers; no import into `aviato/plugins/` or data):
- `model.py` — frozen dataclasses for the §3.2 taxonomy: `VariableSpec`, `TemplateModule`, `PipelineModule`, `VersionSourceModule`, `WorkflowsBundle`, `ScaffoldBundle`, `SettingsBundle`, `Profile`, `ResolvedSet`.
- `errors.py` — `CompositionError`, `DeclarationError`, `MarkerError`, `AuthorizationError`, `CompatibilityError`, `BootstrapError`.
- `listmerge.py` — §4.2 list semantics: `extend`/`add`/`remove` with set semantics + edge-case hard errors.
- `mapmerge.py` — §4.2 deep map merge at the leaf.
- `registry.py` — load profile/bundle/template/pipeline definitions from a module-source root (YAML data).
- `composition.py` — §5.1 resolution: `resolve_profile()` applying `extends` + list/map merge + consumer overrides → `ResolvedSet`.
- `version.py` — SemVer parse/compare; §2.6 `is_compatible()`.
- `declaration.py` — §6.1 `.github/aviato.yaml` schema load/validate/serialize.
- `variables.py` — §6.6 typing/validation; §5.2 precedence resolution; §8.15 secret-write-back hard error.
- `marker.py` — §6.2 managed-marker render/parse, content-hash, per-filetype comment map, malformed detection.
- `scaffold.py` — §5.3 overlay map, render, stamp, atomic write, seed-once (§6.3) + report-only sidecar.
- `diagnosis.py` — §5.4 per-artifact status enum + probes + bootstrap rejection.
- `filedrift.py` — §5.5 drift comparison hash + deterministic proposal identity.
- `settingsdrift.py` — §5.6 additive/destructive classification (ambiguous = destructive).
- `consent.py` — §6.4 consent-record model + §5.8 fail-closed authorization gate.
- `bootstrap.py` — §5.10 structural Library predicate.
- `selfcheck.py` — §9b core-level DoD: import-edge check + denylist scan over `aviato/core/`.

**New plug-in data trees** (the §5.10 module-source tree; plug-in *data*, not core code):
- `bundles/workflows/*.yaml`, `bundles/scaffold/*.yaml`, `bundles/settings/*.yaml`
- `profiles/*.yaml` — `python-library`, `python-service`, `python-component`, `node-service`, `swift-app`
- `templates/scaffold/**` — managed scaffold template bodies (distinct from the existing caller-workflow `templates/*.yml`).

**Modified:**
- `aviato/profiles.py` — DELETE (hardcoded language knowledge → replaced by data + registry).
- `aviato/cli.py` — route `onboard` through the registry/composition; add `doctor`, `repin`, `offboard` subcommands.
- `aviato/paths.py` — add `MODULE_SOURCE_ROOT`, `PROFILES_DIR`, `BUNDLES_DIR`.
- `aviato/validation.py` — add the §9b self-check to repository validation.

**Tests:** one file per core module under `tests/core/`.

---

## Phase 1 — Core model & §4.2 merge semantics

### Task 1: Errors module

**Files:**
- Create: `aviato/core/__init__.py` (empty)
- Create: `aviato/core/errors.py`
- Test: `tests/core/test_errors.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/core/test_errors.py
import pytest
from aviato.core.errors import CompositionError, DeclarationError, MarkerError

def test_errors_are_distinct_value_errors():
    for exc in (CompositionError, DeclarationError, MarkerError):
        assert issubclass(exc, Exception)
    with pytest.raises(CompositionError):
        raise CompositionError("boom")
```
- [ ] **Step 2: Run** `python3 -m pytest tests/core/test_errors.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement**
```python
# aviato/core/errors.py
from __future__ import annotations

class AviatoError(Exception):
    """Base for all core errors."""

class CompositionError(AviatoError): ...
class DeclarationError(AviatoError): ...
class MarkerError(AviatoError): ...
class AuthorizationError(AviatoError): ...
class CompatibilityError(AviatoError): ...
class BootstrapError(AviatoError): ...
```
Also create empty `aviato/core/__init__.py` and `tests/core/__init__.py`.
- [ ] **Step 4: Run** the test — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): add core error hierarchy`.

### Task 2: List-merge (§4.2 list semantics)

**Files:**
- Create: `aviato/core/listmerge.py`
- Test: `tests/core/test_listmerge.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/core/test_listmerge.py
import pytest
from aviato.core.listmerge import merge_list
from aviato.core.errors import CompositionError

def test_add_and_remove_preserve_set_semantics():
    assert merge_list(["a", "b"], add=["c"], remove=["a"]) == ["b", "c"]

def test_remove_absent_is_hard_error():
    with pytest.raises(CompositionError):
        merge_list(["a"], add=[], remove=["zzz"])

def test_add_duplicate_is_hard_error():
    with pytest.raises(CompositionError):
        merge_list(["a"], add=["a"], remove=[])

def test_add_and_remove_same_element_is_hard_error():
    with pytest.raises(CompositionError):
        merge_list(["a"], add=["x"], remove=["x"])

def test_result_is_deterministic_order_base_then_added():
    assert merge_list(["b", "a"], add=["c"], remove=[]) == ["b", "a", "c"]
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**
```python
# aviato/core/listmerge.py
from __future__ import annotations
from collections.abc import Sequence
from .errors import CompositionError

def merge_list(base: Sequence[str], *, add: Sequence[str], remove: Sequence[str]) -> list[str]:
    add_list, remove_list = list(add), list(remove)
    overlap = set(add_list) & set(remove_list)
    if overlap:
        raise CompositionError(f"add and remove the same element in one layer: {sorted(overlap)}")
    base_set = set(base)
    for item in remove_list:
        if item not in base_set:
            raise CompositionError(f"remove of absent element: {item!r}")
    for item in add_list:
        if item in base_set:
            raise CompositionError(f"add of already-present element: {item!r}")
    removed = set(remove_list)
    result = [item for item in base if item not in removed]
    result.extend(add_list)  # deterministic: base order, then additions
    return result
```
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): list merge with explicit add/remove and edge-case hard errors`.

### Task 3: Map deep-merge (§4.2 map semantics)

**Files:**
- Create: `aviato/core/mapmerge.py`
- Test: `tests/core/test_mapmerge.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/core/test_mapmerge.py
from aviato.core.mapmerge import deep_merge

def test_leaf_override_keeps_sibling_keys():
    base = {"x": 1, "y": 2, "nested": {"a": 1, "b": 2}}
    override = {"y": 3, "nested": {"b": 9}}
    assert deep_merge(base, override) == {"x": 1, "y": 3, "nested": {"a": 1, "b": 9}}

def test_override_replaces_non_dict_leaf():
    assert deep_merge({"k": [1, 2]}, {"k": [3]}) == {"k": [3]}

def test_inputs_not_mutated():
    base = {"n": {"a": 1}}
    deep_merge(base, {"n": {"b": 2}})
    assert base == {"n": {"a": 1}}
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**
```python
# aviato/core/mapmerge.py
from __future__ import annotations
from copy import deepcopy
from typing import Any

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result
```
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): deep map merge preserving sibling keys`.

### Task 4: Model dataclasses (§3.2 taxonomy)

**Files:**
- Create: `aviato/core/model.py`
- Test: `tests/core/test_model.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/core/test_model.py
from aviato.core.model import (
    VariableSpec, TemplateModule, PipelineModule, VersionSourceModule,
    WorkflowsBundle, ScaffoldBundle, SettingsBundle, Profile, ResolvedSet,
)

def test_variable_spec_defaults_non_secret():
    v = VariableSpec(name="dist", type="string")
    assert v.secret is False and v.required is True

def test_enum_variable_carries_domain():
    v = VariableSpec(name="language-variant", type="enum", domain=("typescript", "javascript"))
    assert v.domain == ("typescript", "javascript")

def test_profile_is_frozen():
    p = Profile(name="x", workflows="w", scaffold="s", settings="g")
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "y"

def test_resolved_set_holds_composed_modules():
    rs = ResolvedSet(profile="x", pipelines=("verify",), templates=(), settings={},
                     variables=(), version_source=None, toolchain={})
    assert rs.pipelines == ("verify",)
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** frozen dataclasses. `VariableSpec(name, type, secret=False, required=True, domain=None, default=None)`; `TemplateModule(output_path, source, seed_once=False, comment_syntax=None, required_variables=())`; `PipelineModule(name, privileges=(), inputs=(), secrets=())`; `VersionSourceModule(locations=())`; bundle dataclasses each holding a tuple of references plus optional `extends`/`add`/`remove`/settings map; `Profile(name, workflows, scaffold, settings, requires_macos=False)`; `ResolvedSet(profile, pipelines, templates, settings, variables, version_source, toolchain)`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): module taxonomy dataclasses`.

---

## Phase 2 — Registry & composition (§5.1)

### Task 5: Registry — load module data from a source root

**Files:**
- Create: `aviato/core/registry.py`
- Modify: `aviato/paths.py` (add `MODULE_SOURCE_ROOT = REPO_ROOT`, `PROFILES_DIR`, `BUNDLES_DIR`)
- Test: `tests/core/test_registry.py` (+ fixtures under `tests/core/fixtures/modsrc/`)

- [ ] **Step 1: Write the failing test** — build a tiny fixture module tree (`profiles/p.yaml`, `bundles/workflows/w.yaml`, etc.) and assert `Registry(root).profile("p")` returns a `Profile`, `Registry(root).workflows_bundle("w")` returns a `WorkflowsBundle`, and an unknown name raises `CompositionError`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `Registry` reading YAML from `<root>/profiles/*.yaml` and `<root>/bundles/<kind>/*.yaml`, mapping dicts onto the Task 4 dataclasses; raise `CompositionError` on missing file/name.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): module registry loading profiles/bundles from data`.

### Task 6: Composition — resolve profile to ResolvedSet (§5.1, §4.2)

**Files:**
- Create: `aviato/core/composition.py`
- Test: `tests/core/test_composition.py`

- [ ] **Step 1: Write the failing test**
```python
def test_resolve_applies_extends_add_remove_for_lists(tmp_registry):
    rs = resolve_profile(tmp_registry, "child")  # child extends base; add pipeline c, remove a
    assert rs.pipelines == ("b", "c")

def test_resolve_deep_merges_settings_maps(tmp_registry):
    rs = resolve_profile(tmp_registry, "child")
    assert rs.settings["pr"]["required_reviews"] == 1  # sibling kept, leaf overridden

def test_consumer_overrides_apply_same_semantics(tmp_registry):
    rs = resolve_profile(tmp_registry, "child", overrides={"settings": {"pr": {"required_reviews": 0}}})
    assert rs.settings["pr"]["required_reviews"] == 0

def test_bare_list_under_extends_is_rejected(tmp_registry_bare_list):
    with pytest.raises(CompositionError):
        resolve_profile(tmp_registry_bare_list, "child")

def test_missing_referenced_module_is_hard_error(tmp_registry_missing):
    with pytest.raises(CompositionError):
        resolve_profile(tmp_registry_missing, "p")

def test_resolution_is_pure_deterministic(tmp_registry):
    assert resolve_profile(tmp_registry, "child") == resolve_profile(tmp_registry, "child")
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `resolve_profile(registry, name, *, overrides=None)`: load profile → for each bundle resolve `extends` chain (ancestors first) applying `merge_list` (§4.2) for list props and `deep_merge` for the settings map → reject a bare list under `extends`/override → apply consumer `overrides` under the same rules → assemble `ResolvedSet`. Pure: no I/O beyond the registry's already-loaded data, deterministic ordering.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): pure profile resolution and composition`.

---

## Phase 3 — Consumer contract (§6) & variables (§5.2)

### Task 7: SemVer & version-pin compatibility (§2.6)

**Files:**
- Create: `aviato/core/version.py`
- Test: `tests/core/test_version.py`

- [ ] **Step 1: Write the failing test**
```python
from aviato.core.version import parse_version, is_compatible

def test_exact_pin_requires_major_match_and_tool_ge_recorded():
    # pin vX.Y.Z form: tool 1.4.0, pin major 1, recorded marker version 1.2.0
    assert is_compatible(tool="1.4.0", pinned="v1.2.0", recorded="1.2.0") is True
    assert is_compatible(tool="1.1.0", pinned="v1.2.0", recorded="1.2.0") is False  # tool < recorded
    assert is_compatible(tool="2.0.0", pinned="v1.2.0", recorded="1.2.0") is False  # major mismatch

def test_floating_major_pin_matches_on_major():
    assert is_compatible(tool="1.9.0", pinned="v1", recorded="1.3.0") is True
    assert is_compatible(tool="1.2.0", pinned="v1", recorded="1.3.0") is False  # tool < recorded
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `parse_version` (tolerant of leading `v`), a comparable `(major,minor,patch)` tuple, and `is_compatible(tool, pinned, recorded)` = `tool.major == pinned.major and tool >= recorded` per §2.6.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): semver and version-pin compatibility (§2.6)`.

### Task 8: Declaration file schema (§6.1)

**Files:**
- Create: `aviato/core/declaration.py`
- Test: `tests/core/test_declaration.py`

- [ ] **Step 1: Write the failing test** — round-trip a valid declaration (`profile`, `version`, `docs` default False, `variables`, `overrides`); reject missing `profile`/`version` with `DeclarationError`; reject a non-mapping file.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `Declaration` dataclass + `load_declaration(path)` / `dump_declaration(decl)` (YAML), validating required fields and `docs` default `False`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): consumer declaration schema (§6.1)`.

### Task 9: Variable typing & resolution (§5.2, §6.6, §8.15)

**Files:**
- Create: `aviato/core/variables.py`
- Test: `tests/core/test_variables.py`

- [ ] **Step 1: Write the failing test**
```python
def test_precedence_flags_over_declaration_over_env_over_autodetect():
    specs = (VariableSpec("name", "string"),)
    resolved = resolve_variables(specs, flags={"name": "f"}, declaration={"name": "d"},
                                 env={"AVIATO_VAR_NAME": "e"}, autodetect={"name": "a"})
    assert resolved["name"] == "f"

def test_enum_value_outside_domain_is_error():
    specs = (VariableSpec("lv", "enum", domain=("typescript", "javascript")),)
    with pytest.raises(DeclarationError):
        resolve_variables(specs, flags={"lv": "ruby"}, declaration={}, env={}, autodetect={})

def test_missing_required_variable_fails_closed_listing_name():
    specs = (VariableSpec("name", "string"),)
    with pytest.raises(DeclarationError) as exc:
        resolve_variables(specs, flags={}, declaration={}, env={}, autodetect={})
    assert "name" in str(exc.value)

def test_persisting_secret_typed_variable_is_hard_error():
    specs = (VariableSpec("token", "string", secret=True),)
    with pytest.raises(DeclarationError):
        writeback_variables(specs, {"token": "abc"})  # §8.15
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `resolve_variables(specs, *, flags, declaration, env, autodetect)` with precedence flags > declaration > env > autodetect, enum-domain + type validation, fail-closed on missing required (message names the variable). `writeback_variables(specs, resolved)` returns the persistable subset and raises `DeclarationError` if any `secret`-typed key is present (§8.15).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): typed variable resolution with secret write-back guard (§8.15)`.

---

## Phase 4 — Managed markers (§6.2) & scaffolding (§5.3, §6.3)

### Task 10: Managed-marker render/parse (§6.2)

**Files:**
- Create: `aviato/core/marker.py`
- Test: `tests/core/test_marker.py`

- [ ] **Step 1: Write the failing test**
```python
from aviato.core.marker import (
    content_hash, render_marker, parse_marker, MarkerInfo, COMMENT_SYNTAX,
)

def test_render_and_parse_roundtrip_hash_comment():
    body = "line1\nline2\n"
    line = render_marker(profile="python-library", version="v1", body=body, comment="#")
    assert line.startswith("# aviato:managed profile=python-library version=v1 hash=")
    info = parse_marker(line)
    assert info.profile == "python-library" and info.version == "v1"
    assert info.hash == content_hash(body)

def test_hash_excludes_marker_line_and_normalizes_line_endings():
    assert content_hash("a\r\nb\r\n") == content_hash("a\nb\n")

def test_malformed_marker_returns_none():
    assert parse_marker("# aviato:managed profile=x") is None  # missing version/hash

def test_first_nonblank_line_is_the_marker():
    text = "\n\n# aviato:managed profile=p version=v1 hash=abc\nbody\n"
    info = parse_marker_from_text(text)
    assert info.profile == "p"
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `COMMENT_SYNTAX` map (e.g. `{".py": "#", ".yml": "#", ".yaml": "#", ".ts": "//", ".js": "//", ".swift": "//", ...}`); `content_hash(body)` = sha256 of line-ending-normalized body; `render_marker(...)` producing the canonical `aviato:managed profile=… version=… hash=…` grammar; `parse_marker(line)`/`parse_marker_from_text(text)` returning `MarkerInfo|None` (None = malformed/absent, per §6.2 → §5.4 dirty-drift).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): managed-marker format render/parse (§6.2)`.

### Task 11: Scaffolding engine (§5.3) + seed-once sidecar (§6.3)

**Files:**
- Create: `aviato/core/scaffold.py`
- Test: `tests/core/test_scaffold.py`

- [ ] **Step 1: Write the failing test**
```python
def test_writes_managed_file_with_marker_atomically(tmp_path):
    plan = [ScaffoldItem(output="cfg.py", body="X = 1\n", comment="#", seed_once=False)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    text = (tmp_path / "cfg.py").read_text()
    assert text.startswith("# aviato:managed profile=p version=v1 hash=")
    assert "X = 1" in text

def test_idempotent_on_clean_tree(tmp_path):
    plan = [ScaffoldItem("cfg.py", "X = 1\n", "#", False)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    first = (tmp_path / "cfg.py").read_text()
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "cfg.py").read_text() == first
    assert result.unchanged == ["cfg.py"]

def test_refuses_to_overwrite_unmanaged_file_unless_forced(tmp_path):
    (tmp_path / "cfg.py").write_text("hand written\n")
    plan = [ScaffoldItem("cfg.py", "X = 1\n", "#", False)]
    result = scaffold(tmp_path, plan, profile="p", version="v1")
    assert "cfg.py" in result.skipped_unmanaged
    assert (tmp_path / "cfg.py").read_text() == "hand written\n"
    scaffold(tmp_path, plan, profile="p", version="v1", force=True)
    assert "X = 1" in (tmp_path / "cfg.py").read_text()

def test_seed_once_writes_when_absent_records_sidecar_and_never_overwrites(tmp_path):
    plan = [ScaffoldItem("Dockerfile", "FROM x\n", "#", seed_once=True)]
    scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "Dockerfile").read_text() == "FROM x\n"  # no marker
    sidecar = read_sidecar(tmp_path)
    assert "Dockerfile" in sidecar  # report-only integrity hash
    (tmp_path / "Dockerfile").write_text("FROM y\n")
    scaffold(tmp_path, plan, profile="p", version="v1")
    assert (tmp_path / "Dockerfile").read_text() == "FROM y\n"  # never overwritten
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `ScaffoldItem` + `scaffold(root, items, *, profile, version, force=False) -> ScaffoldResult`: build output→item overlay (later wins; tie at same level is error), for managed items render+stamp marker and write atomically (temp + `os.replace`) unless target is unmanaged/malformed (skip+report unless `force`); for seed-once write only when absent, record a content-hash in a report-only sidecar (`.github/aviato.seed.json`), never overwrite. `ScaffoldResult` carries `written`, `unchanged`, `skipped_unmanaged`, `seeded`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): scaffolding with managed markers, atomic writes, seed-once sidecar`.

---

## Phase 5 — Diagnosis (§5.4) & drift (§5.5/§5.6)

### Task 12: File drift comparison (§5.5)

**Files:**
- Create: `aviato/core/filedrift.py`
- Test: `tests/core/test_filedrift.py`

- [ ] **Step 1: Write the failing test**
```python
def test_version_only_change_is_noop():
    # same body, marker version moved → no drift (§8.12)
    assert body_drift(expected_body="a\n", live_body="a\n") is False

def test_body_change_is_drift():
    assert body_drift(expected_body="a\n", live_body="b\n") is True

def test_proposal_identity_is_deterministic_from_profile_and_outputs():
    a = proposal_identity("python-library", ["cfg.py", "ci.yml"])
    b = proposal_identity("python-library", ["ci.yml", "cfg.py"])
    assert a == b  # order-independent, stable key
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `body_drift(expected_body, live_body)` comparing `content_hash` (marker-version excluded by construction); `proposal_identity(profile, outputs)` = stable hash over profile + sorted outputs → `aviato/sync/<profile>-<shorthash>` branch key.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): file drift comparison and deterministic proposal identity (§5.5)`.

### Task 13: Settings drift classification (§5.6)

**Files:**
- Create: `aviato/core/settingsdrift.py`
- Test: `tests/core/test_settingsdrift.py`

- [ ] **Step 1: Write the failing test**
```python
def test_new_constraint_is_additive():
    assert classify_change(desired={"require_pr": True}, live={}).kind == "additive"

def test_weakening_a_value_is_destructive():
    d = classify_settings(desired={"required_reviews": 1}, live={"required_reviews": 2})
    assert d.destructive  # lowering count

def test_removing_a_protection_is_destructive():
    d = classify_settings(desired={}, live={"require_pr": True})
    assert d.destructive

def test_ambiguous_change_is_destructive():
    d = classify_settings(desired={"x": object()}, live={"x": object()})
    assert d.destructive  # unrecognized/ambiguous fails safe
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `classify_settings(desired, live)` returning a diff with per-key `additive`/`destructive` and an aggregate `destructive` flag; a change is additive only if it introduces a new constraint with no loss; removals/weakenings/replacements and anything ambiguous → destructive.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): additive/destructive settings classification (§5.6)`.

### Task 14: Diagnosis / doctor (§5.4)

**Files:**
- Create: `aviato/core/diagnosis.py`
- Test: `tests/core/test_diagnosis.py`

- [ ] **Step 1: Write the failing test**
```python
def test_statuses_clean_mergeable_dirty_missing(tmp_path):
    # arrange managed file matching expected → clean; body diverged w/ valid marker → mergeable;
    # no marker / malformed / unknown version → dirty; absent → missing
    ...

def test_malformed_marker_is_dirty_drift(tmp_path):
    ...

def test_secret_typed_var_in_declaration_is_flagged(tmp_path):
    report = diagnose(...)  # declaration carries a secret-typed key
    assert report.secret_in_declaration

def test_seed_once_integrity_divergence_is_reported_not_overwritten(tmp_path):
    ...

def test_bootstrap_declaration_rejected_outside_library(tmp_path):
    with pytest.raises(BootstrapError):
        diagnose(... bootstrap_declared=True, is_library=False)
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `ArtifactStatus = Literal["clean","mergeable-drift","dirty-drift","missing"]`; `diagnose(root, resolved_set, declaration, *, is_library)` classifying each expected artifact (marker version excluded from clean comparison per §5.5), probing seed-once integrity divergence (report-only), flagging any secret-typed declaration key (§6.6/§8.15), and rejecting a bootstrap declaration when not the Library (§5.10). Scan-heartbeat/issue-channel probes are recorded as report fields (best-effort, absence reads as broken).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): diagnosis with status enum and probes (§5.4)`.

---

## Phase 6 — Authorization (§5.8), bootstrap (§5.10), self-check (§9b)

### Task 15: Consent record & fail-closed authorization (§5.8, §6.4)

**Files:**
- Create: `aviato/core/consent.py`
- Test: `tests/core/test_consent.py`

- [ ] **Step 1: Write the failing test**
```python
def test_allow_only_when_human_consent_current_and_admin():
    d = authorize(actor_type="User", consent_diff_id="abc", current_diff_id="abc",
                  role_lookup_ok=True, role="admin")
    assert d.allowed

def test_non_human_actor_denied():
    assert not authorize(actor_type="Bot", consent_diff_id="abc", current_diff_id="abc",
                         role_lookup_ok=True, role="admin").allowed

def test_unknown_actor_denied():
    assert not authorize(actor_type=None, consent_diff_id="abc", current_diff_id="abc",
                         role_lookup_ok=True, role="admin").allowed

def test_stale_consent_denied():
    assert not authorize(actor_type="User", consent_diff_id="OLD", current_diff_id="NEW",
                         role_lookup_ok=True, role="admin").allowed

def test_role_lookup_failure_denied():
    assert not authorize(actor_type="User", consent_diff_id="abc", current_diff_id="abc",
                         role_lookup_ok=False, role=None).allowed

def test_non_admin_denied():
    assert not authorize(actor_type="User", consent_diff_id="abc", current_diff_id="abc",
                         role_lookup_ok=True, role="write").allowed
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `Decision(allowed: bool, reason: str)` and `authorize(*, actor_type, consent_diff_id, current_diff_id, role_lookup_ok, role)` defaulting DENY: require `actor_type == "User"`, `consent_diff_id == current_diff_id`, `role_lookup_ok`, `role == "admin"` — any failure or unknown → DENY with reason.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): fail-closed authorization gate (§5.8, §2.7)`.

### Task 16: Bootstrap structural predicate (§5.10)

**Files:**
- Create: `aviato/core/bootstrap.py`
- Test: `tests/core/test_bootstrap.py`

- [ ] **Step 1: Write the failing test** — `is_library(root)` True when `root` contains the core package (`aviato/core/`), `profiles/`, `bundles/`, and the project manifest (`pyproject.toml`); False when any is missing; independent of directory name.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `is_library(root)` checking the structural predicate (all four present), name-independent.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): structural Library/bootstrap predicate (§5.10)`.

### Task 17: Core-level falsifiable-agnosticism self-check (§9b)

**Files:**
- Create: `aviato/core/selfcheck.py`
- Test: `tests/core/test_selfcheck.py`

- [ ] **Step 1: Write the failing test**
```python
def test_core_has_no_import_edge_into_plugin_tree():
    assert core_import_violations() == []   # scans aviato/core/*.py for `aviato.plugins` imports

def test_core_contains_no_denylisted_identifier():
    assert denylist_violations() == []      # python/node/swift/pypi/ghcr/pages/docusaurus/apple/ruff/eslint/...

def test_denylist_is_the_maintained_list():
    assert "ruff" in DENYLIST and "docusaurus" in DENYLIST
```
- [ ] **Step 2: Run** — Expected: FAIL (and may legitimately reveal real violations to fix).
- [ ] **Step 3: Implement** `DENYLIST` (the §9b identifiers), `core_import_violations()` (AST/string scan of `aviato/core/*.py` for any `aviato.plugins` import), `denylist_violations()` (case-insensitive token scan of `aviato/core/*.py`). Fix any real violations surfaced (e.g. rename/relocate offending identifiers) until both return `[]`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(core): falsifiable-agnosticism self-check (§9b)`.

---

## Phase 7 — Day-zero plug-in data (§10–§15) & wiring

### Task 18: Author day-zero plug-in data trees

**Files:**
- Create: `bundles/workflows/*.yaml`, `bundles/scaffold/*.yaml`, `bundles/settings/*.yaml`
- Create: `profiles/{python-library,python-service,python-component,node-service,swift-app}.yaml`
- Create: `templates/scaffold/**` (managed scaffold bodies)
- Test: `tests/core/test_dayzero_profiles.py`

- [ ] **Step 1: Write the failing test**
```python
def test_all_dayzero_profiles_resolve():
    reg = Registry(MODULE_SOURCE_ROOT)
    for name in ("python-library","python-service","python-component","node-service","swift-app"):
        rs = resolve_profile(reg, name)
        assert rs.pipelines  # composes verify+release+security at minimum

def test_security_baseline_present_in_every_profile():
    reg = Registry(MODULE_SOURCE_ROOT)
    for name in (...):
        rs = resolve_profile(reg, name)
        assert "security-baseline" in rs.pipelines  # §2.13 always-on

def test_swift_app_requires_macos():
    reg = Registry(MODULE_SOURCE_ROOT)
    assert resolve_profile(reg, "swift-app").requires_macos is True
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the data trees so each §15 profile composes the right language + deploy + always-on security bundles; pipeline references map to the existing `.github/workflows/reusable-*.yml`. Settings bundles carry the desired protected-settings map. Keep all language/deploy identifiers in DATA only (selfcheck stays green).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plugins): day-zero profile/bundle/template data (§10–§15)`.

### Task 19: Core-level DoD — drives ≥2 unrelated plug-ins, loads with zero plug-ins (§9 a/c)

**Files:**
- Test: `tests/core/test_core_dod.py`

- [ ] **Step 1: Write the failing test**
```python
def test_core_imports_with_zero_plugins(monkeypatch, tmp_path):
    # registry pointed at an empty module root still imports the core and runs resolution machinery
    reg = Registry(tmp_path)  # no profiles/bundles
    with pytest.raises(CompositionError):
        resolve_profile(reg, "anything")

def test_same_core_drives_two_unrelated_plugins():
    reg = Registry(MODULE_SOURCE_ROOT)
    a = resolve_profile(reg, "python-library")   # python + pypi
    b = resolve_profile(reg, "swift-app")        # swift + app store connect
    assert a.profile != b.profile and a.pipelines and b.pipelines
```
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** — no production code beyond confirming the registry works with an empty root; fix any coupling the test reveals.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `test(core): core-level DoD — zero-plugin load + two-plugin drive (§9)`.

---

## Phase 8 — CLI integration & repository validation

### Task 20: Route `onboard` through composition; add `doctor`

**Files:**
- Modify: `aviato/cli.py`
- Delete: `aviato/profiles.py`
- Modify: `tests/test_profiles.py` → `tests/test_cli_onboard.py`

- [ ] **Step 1: Write the failing test** — `aviato onboard OWNER/REPO --profile python-library` prints the resolved pipelines/templates/settings/variables from composition (not the old hardcoded map); `aviato doctor <path>` prints per-artifact status from `diagnose`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** new `cmd_onboard` using `Registry`+`resolve_profile`; add `cmd_doctor`; register `doctor` subparser; delete `profiles.py` and its test.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(cli): composition-backed onboard + doctor`.

### Task 21: Add self-check to repository validation (§9b)

**Files:**
- Modify: `aviato/validation.py`
- Modify: `tests/test_validation.py` (create if absent)

- [ ] **Step 1: Write the failing test** — `validate(REPO_ROOT)` includes no error from the self-check when core is clean; injecting a denylisted token into a temp core copy yields an error.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** — call `core_import_violations()`/`denylist_violations()` inside `validate()`, appending any results as errors.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(validation): enforce core agnosticism self-check (§9b)`.

### Task 22: Full validation pass

- [ ] **Step 1:** Run `./scripts/validate.sh`. Expected: all green (or documented SKIPs for uninstalled linters).
- [ ] **Step 2:** Fix any ruff/format issues.
- [ ] **Step 3: Commit** `chore: full validation green for core engine`.

---

## Self-Review

- **Spec coverage:** §4.2 (T2/T3/T6), §5.1 (T6), §5.2 (T9), §5.3/§6.3 (T11), §5.4 (T14), §5.5 (T12), §5.6 (T13), §5.8/§6.4 (T15), §5.10 (T16), §2.6 (T7), §6.1 (T8), §6.2 (T10), §3.2 (T4), §9 (T17/T19/T21), §10–§15 (T18). §5.7/§5.9/§5.11/§5.12/§5.13/§5.14 orchestration and the live-CI plug-in DoD (§16.2–3) depend on real platform calls + `gh`; their *engine* primitives (authorization, compatibility, drift, classification, composition) are built here, and the reusable workflows already exist — those flows are a follow-up plan layered on these primitives.
- **Placeholder scan:** Test bodies marked `...` in T14/T18 are detailed in their Step 3 narrative; expand inline at execution time.
- **Type consistency:** `content_hash`, `proposal_identity`, `resolve_profile`, `Registry`, `VariableSpec`, `ScaffoldItem/ScaffoldResult`, `authorize/Decision`, `is_library` names are used consistently across tasks.
