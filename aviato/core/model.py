from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Literal, NoReturn

VariableType = Literal["string", "boolean", "enum"]
VariableValue = str | bool | None


class FrozenDict(Mapping[str, Any]):
    """A recursively immutable mapping with ordinary mapping equality/access."""

    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        if any(not isinstance(key, str) for key in values):
            raise TypeError("FrozenDict requires string keys; keys are never coerced")
        self._data = {key: deep_freeze(value) for key, value in values.items()}

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, _key: str, _value: Any) -> NoReturn:
        raise TypeError("FrozenDict is immutable")

    def __delitem__(self, _key: str) -> NoReturn:
        raise TypeError("FrozenDict is immutable")

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenDict:
        return self

    def __repr__(self) -> str:
        return repr(self._data)


class FrozenList(tuple[Any, ...]):
    """Tuple storage with list-like mutation methods that fail explicitly."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return False

    __hash__ = tuple.__hash__

    def append(self, _value: Any) -> NoReturn:
        raise TypeError("FrozenList is immutable")

    def extend(self, _values: Any) -> NoReturn:
        raise TypeError("FrozenList is immutable")

    def insert(self, _index: int, _value: Any) -> NoReturn:
        raise TypeError("FrozenList is immutable")

    def pop(self, _index: int = -1) -> NoReturn:
        raise TypeError("FrozenList is immutable")

    def remove(self, _value: Any) -> NoReturn:
        raise TypeError("FrozenList is immutable")

    def clear(self) -> NoReturn:
        raise TypeError("FrozenList is immutable")


def deep_freeze(value: Any) -> Any:
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (list, tuple)):
        return FrozenList(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(item) for item in value)
    return value


def deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {deep_thaw(item) for item in value}
    return value


class UnknownValue(Enum):
    """Singleton marker for a variable whose value is not yet known."""

    VALUE = "unknown"

    def __repr__(self) -> str:
        return "Unknown"

    def __str__(self) -> str:
        return "Unknown"

    def __bool__(self) -> bool:
        raise TypeError("Unknown cannot be collapsed to a boolean")


Unknown: Final[UnknownValue] = UnknownValue.VALUE


@dataclass(frozen=True)
class PartialVariableResolution:
    """Typed variable values available to a non-applicable partial preview."""

    values: dict[str, VariableValue | UnknownValue]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class VariableSpec:
    """A typed declaration variable (§6.6)."""

    name: str
    type: VariableType
    secret: bool = False
    required: bool = True
    domain: tuple[str, ...] | None = None
    default: Any = None


@dataclass(frozen=True)
class TemplateModule:
    """One generated artifact's content source + render inputs (§3.2)."""

    output_path: str
    source: str
    seed_once: bool = False
    comment: str | None = None
    required_variables: tuple[str, ...] = ()
    # Variable-conditional inclusion (§12.2): the template applies only when every
    # (variable, value) pair matches the resolved variables. Empty = always applies.
    when: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class WorkflowEnvelopeModule:
    """Shared, non-executable structure for one generated Actions caller."""

    name: str
    identity: str
    output_path: str
    display_name: str
    permissions: tuple[tuple[str, str], ...] = ()
    concurrency: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class WorkflowJobModule:
    """Data-only ownership metadata for one pipeline-contributed job."""

    name: str
    identity: str
    fragment: str
    needs: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    runner: str | None = None
    environment: str | None = None
    environment_input: str | None = None
    status_check: str | None = None


@dataclass(frozen=True)
class PipelineModule:
    """One reusable automation pipeline with declared privileges (§3.2, §11.3)."""

    name: str
    privileges: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    runner: str | None = None
    # The branch-protection status-check context this pipeline produces (§10), e.g.
    # ``ci / <Verify Job>``. Composition unions these into required_status_checks so
    # the merge gate requires exactly the jobs the profile actually runs. None = the
    # pipeline gates nothing (release/publish run after merge).
    status_check: str | None = None
    # §2.13: a pipeline the data declares always-on (e.g. the security baseline) must
    # survive every composition — resolution refuses to remove it. Data-driven so the
    # agnostic core never names which capability is mandatory.
    always_on: bool = False
    # §17 (R9-20): the protected GitHub-Environments name this pipeline requires. DATA, not core
    # knowledge — the agnostic core never names a concrete day-zero environment; the value comes from
    # plug-in data and the binding probes the environment's existence + required-reviewer settings.
    # The core just relays the per-pipeline string (None = no environment prerequisite).
    environment: str | None = None
    # Optional resolved profile variable that overrides ``environment``. This keeps the
    # binding data-driven while allowing a caller workflow's rendered environment input
    # to select the actual protected environment (for example a production deploy).
    environment_input: str | None = None
    identity: str | None = None
    envelope: str | None = None
    triggers: Mapping[str, Any] = field(default_factory=dict)
    jobs: tuple[WorkflowJobModule, ...] = ()
    required_pipelines: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    declared_aggregates: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "triggers", deep_freeze(self.triggers))


@dataclass(frozen=True)
class VersionSourceModule:
    """Where and how a language records its version (§3.2, §3.3)."""

    locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowsBundle:
    """The set of automation pipelines a profile attaches (§3.2)."""

    name: str
    extends: str | None = None
    pipelines: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScaffoldBundle:
    """The set of managed files a profile materializes (§3.2)."""

    name: str
    extends: str | None = None
    templates: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingsBundle:
    """The desired protected-resource settings a profile enforces (§3.2)."""

    name: str
    extends: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", deep_freeze(self.settings))


@dataclass(frozen=True)
class Profile:
    """A thin manifest naming one bundle of each kind; no logic (§3.2, §4.1)."""

    name: str
    identity: str
    workflows: str
    scaffold: str
    settings: str
    workflow_schema: int = 1
    # review #17: a profile carries NO runner-OS flag. "Does this need a macOS runner?" is derived
    # from the resolved pipelines' data-driven PipelineModule.runner (§11.5), not a target-OS
    # boolean baked into the agnostic core model (adding e.g. a Windows target must never edit core).


@dataclass(frozen=True)
class ResolvedSet:
    """The fully-resolved output of profile resolution (§5.1)."""

    profile: str
    pipelines: tuple[str, ...]
    templates: tuple[TemplateModule, ...]
    settings: Mapping[str, Any]
    variables: tuple[VariableSpec, ...]
    version_source: VersionSourceModule | None
    toolchain: Mapping[str, Any]
    pipeline_modules: tuple[PipelineModule, ...] = ()
    workflow_schema: int = 1
    scaffold_templates: tuple[TemplateModule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", deep_freeze(self.settings))
        object.__setattr__(self, "toolchain", deep_freeze(self.toolchain))
