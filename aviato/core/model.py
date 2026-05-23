from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VariableType = Literal["string", "boolean", "enum"]


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
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """A thin manifest naming one bundle of each kind; no logic (§3.2, §4.1)."""

    name: str
    workflows: str
    scaffold: str
    settings: str
    # review #17: a profile carries NO runner-OS flag. "Does this need a macOS runner?" is derived
    # from the resolved pipelines' data-driven PipelineModule.runner (§11.5), not a target-OS
    # boolean baked into the agnostic core model (adding e.g. a Windows target must never edit core).


@dataclass(frozen=True)
class ResolvedSet:
    """The fully-resolved output of profile resolution (§5.1)."""

    profile: str
    pipelines: tuple[str, ...]
    templates: tuple[TemplateModule, ...]
    settings: dict[str, Any]
    variables: tuple[VariableSpec, ...]
    version_source: VersionSourceModule | None
    toolchain: dict[str, Any]
    pipeline_modules: tuple[PipelineModule, ...] = ()
