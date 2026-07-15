from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from .inventory import ManagedInventory, owned_rulesets_by_identity
from .model import deep_freeze, deep_thaw
from .outcomes import OperationStatus, RulesetExecutionResult, RulesetOperationResult
from .ports import RepositoryIdentity

ComparisonState = Literal["equal", "changed", "indeterminate"]
RulesetAction = Literal["noop", "create", "update", "delete"]
OperationDisposition = Literal["ready", "manual", "indeterminate"]

_SECURITY_KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")
_RULESET_ID_KEY = "id"
_RESPONSE_METADATA_KEYS = frozenset(
    {
        "created_at",
        "updated_at",
        "html_url",
        "url",
        "_links",
        "display",
        "node_id",
        "source",
        "source_type",
        "current_user_can_bypass",
    }
)
_EVIDENCE_EXCLUDED_KEYS = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "html_url",
        "url",
        "_links",
        "display",
        "current_user_can_bypass",
    }
)


@dataclass(frozen=True)
class ConditionNormalization:
    state: Literal["normalized", "indeterminate"]
    value: Mapping[str, Any] | None = None
    detail: str = ""


@dataclass(frozen=True)
class RulesetChange:
    field: str
    before: Any
    after: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "before", deep_freeze(self.before))
        object.__setattr__(self, "after", deep_freeze(self.after))


@dataclass(frozen=True)
class RuleComparison:
    state: ComparisonState
    changes: tuple[RulesetChange, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class RulesetIdentity:
    name: str
    target: str
    live_id: int | None = None
    live_node_id: str | None = None
    source_type: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("ruleset identity requires a non-empty name")
        if self.target not in {"branch", "tag"}:
            raise ValueError("ruleset identity target must be branch or tag")
        if self.live_id is not None and (isinstance(self.live_id, bool) or self.live_id <= 0):
            raise ValueError("live ruleset id must be a positive integer")
        for field_name, value in (
            ("live_node_id", self.live_node_id),
            ("source_type", self.source_type),
            ("source", self.source),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"ruleset identity {field_name} must be a non-empty string")

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.target


@dataclass(frozen=True)
class RulesetOperation:
    operation_id: str
    identity: RulesetIdentity
    action: RulesetAction
    comparison: RuleComparison
    before_fingerprint: str | None
    desired_fingerprint: str | None
    desired_payload: Mapping[str, Any] | None
    disposition: OperationDisposition = "ready"
    reason: str = ""
    indeterminate_evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.desired_payload is not None:
            object.__setattr__(self, "desired_payload", deep_freeze(self.desired_payload))
        if self.indeterminate_evidence is not None:
            object.__setattr__(self, "indeterminate_evidence", deep_freeze(self.indeterminate_evidence))


@dataclass(frozen=True)
class RulesetPlan:
    repository: RepositoryIdentity
    tool_version: str
    declaration_pin: str
    snapshot_sha: str
    operations: tuple[RulesetOperation, ...]
    canonical_json: str
    plan_id: str

    @property
    def applicable(self) -> bool:
        return all(operation.disposition == "ready" for operation in self.operations)


@dataclass(frozen=True)
class RulesetDeletionBinding:
    repository: RepositoryIdentity
    ruleset: RulesetIdentity
    plan_id: str
    prior_snapshot_sha: str
    prior_payload_fingerprint: str
    live_payload_fingerprint: str


ReceiptVerifier = Callable[[object, RulesetDeletionBinding], bool]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("ruleset security mappings require string keys")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"ruleset security value has unsupported type {type(value).__name__}")


def _canonical_set(values: Sequence[Any]) -> list[Any]:
    return sorted((_canonical_value(item) for item in values), key=_canonical_json)


def _evidence_value(value: Any) -> Any:
    """Encode invalid input losslessly enough to keep distinct failures distinct."""

    if isinstance(value, Mapping):
        return {
            "mapping": sorted(
                [(_evidence_value(key), _evidence_value(item)) for key, item in value.items()],
                key=_canonical_json,
            )
        }
    if isinstance(value, (list, tuple)):
        return {"sequence": [_evidence_value(item) for item in value]}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, float):
        return {"float": repr(value)}
    if value is None or isinstance(value, (str, int, bool)):
        return {type(value).__name__: value}
    raise ValueError(
        "cannot canonically bind malformed ruleset value of type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _payload_evidence(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return _evidence_value(value)
    sanitized = {
        key: item
        for key, item in value.items()
        if not isinstance(key, str) or key not in _EVIDENCE_EXCLUDED_KEYS
    }
    return _evidence_value(sanitized)


def _normalize_ref_values(values: object, *, target: str, default_branch: str) -> tuple[str, ...]:
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError("ruleset ref_name include/exclude must be string arrays")
    normalized: set[str] = set()
    for item in values:
        if item == "~DEFAULT_BRANCH":
            if target != "branch":
                raise ValueError("~DEFAULT_BRANCH is only valid for branch rulesets")
            normalized.add(f"refs/heads/{default_branch}")
        elif item == "~ALL":
            normalized.add("refs/heads/*" if target == "branch" else "refs/tags/*")
        elif item.startswith("~"):
            raise ValueError(f"unknown ruleset ref token {item!r}")
        else:
            normalized.add(item)
    return tuple(sorted(normalized))


def normalize_conditions(conditions: object, *, target: str, default_branch: str) -> ConditionNormalization:
    try:
        if not isinstance(conditions, Mapping) or set(conditions) != {"ref_name"}:
            raise ValueError("ruleset conditions must contain only ref_name")
        ref_name = conditions["ref_name"]
        if not isinstance(ref_name, Mapping) or set(ref_name) != {"include", "exclude"}:
            raise ValueError("ruleset ref_name conditions require include and exclude")
        value = {
            "ref_name": {
                "include": _normalize_ref_values(ref_name["include"], target=target, default_branch=default_branch),
                "exclude": _normalize_ref_values(ref_name["exclude"], target=target, default_branch=default_branch),
            }
        }
    except (KeyError, TypeError, ValueError) as exc:
        return ConditionNormalization("indeterminate", detail=str(exc))
    return ConditionNormalization("normalized", deep_freeze(value))


def _identity(payload: object, *, source: str) -> tuple[str, str]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{source} ruleset payload must be a mapping")
    name = payload.get("name")
    target = payload.get("target")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{source} ruleset payload requires a non-empty name")
    if target not in {"branch", "tag"}:
        raise ValueError(f"{source} ruleset {name!r} requires target branch or tag")
    return name, target


def _security_payload(
    payload: Mapping[str, Any], *, target: str, default_branch: str
) -> tuple[Mapping[str, Any] | None, str]:
    try:
        missing = [key for key in _SECURITY_KEYS if key not in payload]
        if missing:
            raise ValueError(f"ruleset payload is missing security fields: {missing}")
        if payload.get("target") != target:
            raise ValueError("ruleset payload target changed while normalizing")
        enforcement = payload.get("enforcement")
        if not isinstance(enforcement, str) or not enforcement:
            raise ValueError("ruleset enforcement must be a non-empty string")
        conditions = normalize_conditions(payload.get("conditions"), target=target, default_branch=default_branch)
        if conditions.state == "indeterminate" or conditions.value is None:
            raise ValueError(conditions.detail)
        bypass = payload.get("bypass_actors")
        rules = payload.get("rules")
        if not isinstance(bypass, list) or any(not isinstance(item, Mapping) for item in bypass):
            raise ValueError("ruleset bypass_actors must be an array of mappings")
        if not isinstance(rules, list) or any(not isinstance(item, Mapping) for item in rules):
            raise ValueError("ruleset rules must be an array of mappings")
        security = {
            "name": payload["name"],
            "target": target,
            "enforcement": enforcement,
            "conditions": deep_thaw(conditions.value),
            "bypass_actors": _canonical_set(bypass),
            "rules": _canonical_set(rules),
        }
        for key in sorted(set(payload) - set(_SECURITY_KEYS) - _RESPONSE_METADATA_KEYS - {_RULESET_ID_KEY}):
            security[key] = _canonical_value(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        return None, str(exc)
    return deep_freeze(security), ""


def ruleset_payload_fingerprint(payload: Mapping[str, Any], *, target: str, default_branch: str) -> str:
    security, detail = _security_payload(payload, target=target, default_branch=default_branch)
    if security is None:
        raise ValueError(f"cannot fingerprint indeterminate ruleset payload: {detail}")
    return hashlib.sha256(_canonical_json(deep_thaw(security)).encode("ascii")).hexdigest()


def _diff(before: Any, after: Any, path: str = "") -> tuple[RulesetChange, ...]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[RulesetChange] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else key
            if key not in before:
                changes.append(RulesetChange(child, None, after[key]))
            elif key not in after:
                changes.append(RulesetChange(child, before[key], None))
            else:
                changes.extend(_diff(before[key], after[key], child))
        return tuple(changes)
    if before != after:
        return (RulesetChange(path or "$", before, after),)
    return ()


def _index(payloads: Sequence[Mapping[str, Any]], *, source: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for payload in payloads:
        key = _identity(payload, source=source)
        if key in result:
            raise ValueError(f"duplicate {source} ruleset identity {key!r}")
        result[key] = payload
    return result


def _live_id(payload: Mapping[str, Any] | None) -> int | None:
    if payload is None:
        return None
    value = payload.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _response_identity(
    payload: Mapping[str, Any] | None,
    *,
    repository: RepositoryIdentity,
) -> tuple[str | None, str | None, str | None, str]:
    if payload is None:
        return None, None, None, ""
    fields = (payload.get("node_id"), payload.get("source_type"), payload.get("source"))
    if fields == (None, None, None):
        return None, None, None, "ruleset response is missing repository authority metadata"
    node_id, source_type, source = fields
    if not all(isinstance(value, str) and value for value in fields):
        return None, None, None, "ruleset response identity metadata is incomplete or malformed"
    assert isinstance(node_id, str) and isinstance(source_type, str) and isinstance(source, str)
    if source_type != "Repository":
        return node_id, source_type, source, "ruleset source_type is not Repository"
    if source.casefold() != repository.full_name.casefold():
        return node_id, source_type, source, "ruleset source does not match the bound repository"
    return node_id, source_type, repository.full_name, ""


def _plan_payload(
    repository: RepositoryIdentity,
    tool_version: str,
    declaration_pin: str,
    snapshot_sha: str,
    operations: Sequence[RulesetOperation],
) -> dict[str, Any]:
    return {
        "repository": {
            "database_id": repository.database_id,
            "node_id": repository.node_id,
            "full_name": repository.full_name,
            "default_branch": repository.default_branch,
        },
        "tool_version": tool_version,
        "declaration_pin": declaration_pin,
        "snapshot_sha": snapshot_sha,
        "operations": [
            {
                "operation_id": operation.operation_id,
                "identity": {
                    "name": operation.identity.name,
                    "target": operation.identity.target,
                    "live_id": operation.identity.live_id,
                    "live_node_id": operation.identity.live_node_id,
                    "source_type": operation.identity.source_type,
                    "source": operation.identity.source,
                },
                "action": operation.action,
                "comparison": operation.comparison.state,
                "before_fingerprint": operation.before_fingerprint,
                "desired_fingerprint": operation.desired_fingerprint,
                "desired_payload": (
                    deep_thaw(operation.desired_payload) if operation.desired_payload is not None else None
                ),
                "indeterminate_evidence": (
                    deep_thaw(operation.indeterminate_evidence)
                    if operation.indeterminate_evidence is not None
                    else None
                ),
            }
            for operation in operations
        ],
    }


def build_ruleset_plan(
    *,
    repository: RepositoryIdentity,
    tool_version: str,
    declaration_pin: str,
    snapshot_sha: str,
    desired_payloads: Sequence[Mapping[str, Any]],
    live_payloads: Sequence[Mapping[str, Any]],
    prior_inventory: ManagedInventory | None = None,
    prior_desired_payloads: Sequence[Mapping[str, Any]] = (),
    deletion_receipt: object | None = None,
    receipt_verifier: ReceiptVerifier | None = None,
) -> RulesetPlan:
    if not tool_version or not declaration_pin:
        raise ValueError("ruleset plan requires tool version and declaration pin")
    if len(snapshot_sha) != 40 or any(character not in "0123456789abcdef" for character in snapshot_sha):
        raise ValueError("ruleset plan snapshot SHA must be lowercase 40-hex")
    desired = _index(desired_payloads, source="desired")
    live = _index(live_payloads, source="live")
    prior_desired = _index(prior_desired_payloads, source="prior desired")
    operations: list[RulesetOperation] = []
    keys = sorted(set(desired) | set(live))
    for index, key in enumerate(keys, 1):
        desired_raw = desired.get(key)
        live_raw = live.get(key)
        live_node_id, source_type, source, response_error = _response_identity(
            live_raw,
            repository=repository,
        )
        desired_security, desired_error = (
            _security_payload(desired_raw, target=key[1], default_branch=repository.default_branch)
            if desired_raw is not None
            else (None, "")
        )
        live_security, live_error = (
            _security_payload(live_raw, target=key[1], default_branch=repository.default_branch)
            if live_raw is not None
            else (None, "")
        )
        if response_error:
            live_security = None
            live_error = response_error
        live_id = _live_id(live_raw)
        identity = RulesetIdentity(key[0], key[1], live_id, live_node_id, source_type, source)
        before_fingerprint = (
            hashlib.sha256(_canonical_json(deep_thaw(live_security)).encode("ascii")).hexdigest()
            if live_security is not None
            else None
        )
        desired_fingerprint = (
            hashlib.sha256(_canonical_json(deep_thaw(desired_security)).encode("ascii")).hexdigest()
            if desired_security is not None
            else None
        )
        if (desired_raw is not None and desired_security is None) or (live_raw is not None and live_security is None):
            detail = desired_error or live_error or "ruleset state is indeterminate"
            operation = RulesetOperation(
                f"rule-{index:04d}",
                identity,
                "update" if live_raw is not None else "create",
                RuleComparison("indeterminate", detail=detail),
                before_fingerprint,
                desired_fingerprint,
                desired_security,
                "indeterminate",
                detail,
                {
                    "classification": detail,
                    "desired": _payload_evidence(desired_raw),
                    "live": _payload_evidence(live_raw),
                },
            )
        elif desired_security is None:
            operation = RulesetOperation(
                f"rule-{index:04d}",
                identity,
                "delete",
                RuleComparison("changed", (RulesetChange("$", live_security, None),)),
                before_fingerprint,
                None,
                None,
                "manual",
                "ruleset deletion requires prior ownership and a verified Task 11 receipt",
            )
        elif live_security is None:
            operation = RulesetOperation(
                f"rule-{index:04d}",
                identity,
                "create",
                RuleComparison("changed", (RulesetChange("$", None, desired_security),)),
                None,
                desired_fingerprint,
                desired_security,
            )
        else:
            changes = _diff(live_security, desired_security)
            state: ComparisonState = "equal" if not changes else "changed"
            operation = RulesetOperation(
                f"rule-{index:04d}",
                identity,
                "noop" if not changes else "update",
                RuleComparison(state, changes),
                before_fingerprint,
                desired_fingerprint,
                desired_security,
            )
        operations.append(operation)

    canonical = _canonical_json(
        _plan_payload(repository, tool_version, declaration_pin, snapshot_sha, operations)
    )
    plan_id = hashlib.sha256(canonical.encode("ascii")).hexdigest()

    authorized: list[RulesetOperation] = []
    owned_by_key = owned_rulesets_by_identity(prior_inventory)
    for operation in operations:
        if operation.action != "delete":
            authorized.append(operation)
            continue
        owned = owned_by_key.get(operation.identity.key)
        prior_raw = prior_desired.get(operation.identity.key)
        prior_fingerprint: str | None = None
        if prior_raw is not None:
            try:
                prior_fingerprint = ruleset_payload_fingerprint(
                    prior_raw,
                    target=operation.identity.target,
                    default_branch=repository.default_branch,
                )
            except ValueError:
                prior_fingerprint = None
        reason = operation.reason
        ready = False
        if owned is None:
            reason = "ruleset deletion is manual: valid prior inventory does not own this identity"
        elif prior_fingerprint != owned.payload_fingerprint:
            reason = "ruleset deletion is manual: prior snapshot does not reproduce the inventory fingerprint"
        elif operation.before_fingerprint != owned.payload_fingerprint:
            reason = "ruleset deletion is manual: live payload no longer matches the owned prior payload"
        elif deletion_receipt is None or receipt_verifier is None:
            reason = "ruleset deletion is manual: no Task 11 signature-verified receipt is available"
        else:
            binding = RulesetDeletionBinding(
                repository,
                operation.identity,
                plan_id,
                owned.snapshot_commit,
                owned.payload_fingerprint,
                operation.before_fingerprint or "",
            )
            try:
                ready = receipt_verifier(deletion_receipt, binding) is True
            except Exception:
                ready = False
            if not ready:
                reason = "ruleset deletion is manual: receipt verification failed closed"
        authorized.append(replace(operation, disposition="ready" if ready else "manual", reason=reason))

    return RulesetPlan(
        repository,
        tool_version,
        declaration_pin,
        snapshot_sha,
        tuple(authorized),
        canonical,
        plan_id,
    )


def require_apply_confirmation(
    plans: Sequence[RulesetPlan], *, apply: bool, confirmation: str | None
) -> RulesetPlan | None:
    if not apply:
        return None
    if len(plans) != 1:
        raise ValueError("ruleset apply requires exactly one repository")
    plan = plans[0]
    if confirmation is None:
        raise ValueError(f"ruleset apply requires --confirm {plan.plan_id}")
    if confirmation != plan.plan_id:
        raise ValueError("ruleset confirmation does not match the recomputed plan ID")
    return plan


def verify_recomputed_plan(expected: RulesetPlan, recomputed: RulesetPlan) -> None:
    if expected.plan_id != recomputed.plan_id or expected.canonical_json != recomputed.canonical_json:
        raise ValueError("ruleset plan changed after preview; inspect the new plan and confirm its ID")


def _same_operation_binding(expected: RulesetOperation, current: RulesetOperation) -> bool:
    return replace(expected, operation_id="") == replace(current, operation_id="")


def _verify_evolving_plan(
    original: RulesetPlan,
    current: RulesetPlan,
    *,
    completed: frozenset[tuple[str, str]],
    completed_live_ids: Mapping[tuple[str, str], int],
) -> Mapping[tuple[str, str], RulesetOperation]:
    if (
        original.repository != current.repository
        or original.tool_version != current.tool_version
        or original.declaration_pin != current.declaration_pin
        or original.snapshot_sha != current.snapshot_sha
    ):
        raise ValueError("ruleset plan context changed after preview")
    original_by_key = {operation.identity.key: operation for operation in original.operations}
    current_by_key = {operation.identity.key: operation for operation in current.operations}
    if len(current_by_key) != len(current.operations):
        raise ValueError("recomputed ruleset plan contains duplicate operations")
    unexpected = set(current_by_key) - set(original_by_key)
    if unexpected:
        raise ValueError(f"ruleset plan gained unexpected operations: {sorted(unexpected)!r}")
    for key, expected in original_by_key.items():
        candidate = current_by_key.get(key)
        if key not in completed:
            if candidate is None or not _same_operation_binding(expected, candidate):
                raise ValueError("ruleset plan changed after preview; inspect and confirm a new plan")
            continue
        if expected.action == "delete":
            if candidate is not None:
                raise ValueError("completed ruleset deletion did not converge")
            continue
        if (
            candidate is None
            or candidate.action != "noop"
            or candidate.comparison.state != "equal"
            or candidate.disposition != "ready"
            or candidate.desired_fingerprint != expected.desired_fingerprint
            or candidate.before_fingerprint != expected.desired_fingerprint
            or (expected.identity.live_id is not None and candidate.identity.live_id != expected.identity.live_id)
            or (
                expected.identity.live_node_id is not None
                and candidate.identity.live_node_id != expected.identity.live_node_id
            )
            or (
                expected.identity.live_id is None
                and key in completed_live_ids
                and candidate.identity.live_id != completed_live_ids[key]
            )
        ):
            raise ValueError("completed ruleset write did not converge to the confirmed desired state")
    return current_by_key


def execute_ruleset_plan(
    plan: RulesetPlan,
    *,
    confirmation: str,
    recompute: Callable[[], RulesetPlan],
    upsert: Callable[[RulesetOperation], object],
    delete: Callable[[RulesetOperation], object],
) -> RulesetExecutionResult:
    require_apply_confirmation([plan], apply=True, confirmation=confirmation)
    indeterminate = [operation for operation in plan.operations if operation.disposition == "indeterminate"]
    if indeterminate:
        raise ValueError("indeterminate ruleset comparison cannot apply")
    if any(operation.disposition == "manual" for operation in plan.operations):
        return RulesetExecutionResult(
            plan.plan_id,
            tuple(
                RulesetOperationResult(
                    operation.operation_id,
                    operation.action,
                    f"{operation.identity.name}:{operation.identity.target}",
                    OperationStatus.COMPLETED if operation.action == "noop" else OperationStatus.UNATTEMPTED,
                    operation.reason or "manual operation was not attempted",
                )
                for operation in plan.operations
            ),
        )

    results: list[RulesetOperationResult] = []
    completed: set[tuple[str, str]] = set()
    completed_live_ids: dict[tuple[str, str], int] = {}
    for operation in plan.operations:
        if operation.action == "noop":
            results.append(
                RulesetOperationResult(
                    operation.operation_id,
                    operation.action,
                    f"{operation.identity.name}:{operation.identity.target}",
                    OperationStatus.COMPLETED,
                    "already converged",
                )
            )
            continue
        current = recompute()
        current_by_key = _verify_evolving_plan(
            plan,
            current,
            completed=frozenset(completed),
            completed_live_ids=completed_live_ids,
        )
        for completed_key in completed:
            completed_operation = current_by_key.get(completed_key)
            if completed_operation is not None and completed_operation.identity.live_id is not None:
                completed_live_ids.setdefault(completed_key, completed_operation.identity.live_id)
        current_operation = current_by_key.get(operation.identity.key)
        if current_operation is None or current_operation.disposition != "ready":
            raise ValueError("ruleset operation lost apply authorization during recheck")
        if operation.action == "delete":
            delete(current_operation)
        else:
            upsert(current_operation)
        completed.add(operation.identity.key)
        results.append(
            RulesetOperationResult(
                operation.operation_id,
                operation.action,
                f"{operation.identity.name}:{operation.identity.target}",
                OperationStatus.COMPLETED,
                "applied",
            )
        )
    return RulesetExecutionResult(plan.plan_id, tuple(results))


def security_payload(payload: Mapping[str, Any], *, default_branch: str) -> Mapping[str, Any]:
    """Return the canonical security payload used by a planned write."""

    target = payload.get("target")
    if target not in {"branch", "tag"}:
        raise ValueError("ruleset payload target must be branch or tag")
    normalized, detail = _security_payload(payload, target=target, default_branch=default_branch)
    if normalized is None:
        raise ValueError(detail)
    return normalized
