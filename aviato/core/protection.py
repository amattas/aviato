from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from ..authority_verifier import AUTHORITY_SNAPSHOT_SCHEMA, project_authority_snapshot
from .model import deep_freeze, deep_thaw
from .ports import RepositoryIdentity
from .ruleset_plan import RulesetIdentity, RulesetPlan, build_ruleset_plan

SurfaceStatus = Literal["ready", "manual", "indeterminate"]
OperationStatus = Literal["completed", "failed", "indeterminate", "unattempted"]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class EnvironmentReviewer:
    kind: Literal["user", "team"]
    name: str
    database_id: int
    node_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"user", "team"} or not self.name or self.database_id <= 0 or not self.node_id:
            raise ValueError("environment reviewer requires a concrete user/team identity")


@dataclass(frozen=True)
class ProtectedEnvironment:
    name: str
    reviewers: tuple[EnvironmentReviewer, ...]
    minimum_approvals: int
    prevent_self_review: bool
    branch_patterns: tuple[str, ...]
    tag_patterns: tuple[str, ...]
    wait_timer: int
    custom_rules: tuple[Mapping[str, Any], ...]
    forbid_admin_bypass: bool

    def __post_init__(self) -> None:
        if not self.name or self.minimum_approvals < 1 or self.wait_timer < 0:
            raise ValueError("protected environment requires a name, reviewer count, and nonnegative wait")
        object.__setattr__(self, "custom_rules", tuple(deep_freeze(rule) for rule in self.custom_rules))

    def payload(self) -> Mapping[str, Any]:
        return cast(
            Mapping[str, Any],
            deep_freeze(
                {
                    "reviewers": [
                        {
                            "type": reviewer.kind.title(),
                            "login" if reviewer.kind == "user" else "slug": reviewer.name,
                            "id": reviewer.database_id,
                            "node_id": reviewer.node_id,
                        }
                        for reviewer in sorted(self.reviewers, key=lambda item: (item.kind, item.database_id))
                    ],
                    "minimum_approvals": self.minimum_approvals,
                    "prevent_self_review": self.prevent_self_review,
                    "branch_patterns": sorted(set(self.branch_patterns)),
                    "tag_patterns": sorted(set(self.tag_patterns)),
                    "wait_timer": self.wait_timer,
                    "custom_rules": [deep_thaw(item) for item in self.custom_rules],
                    "can_admins_bypass": False if self.forbid_admin_bypass else None,
                }
            ),
        )


@dataclass(frozen=True)
class ProtectionOperation:
    identity: str
    kind: str
    name: str
    action: Literal["noop", "update", "create", "delete"]
    before: Any
    desired: Any
    before_fingerprint: str
    desired_fingerprint: str
    disposition: SurfaceStatus = "ready"
    detail: str = ""
    ruleset_identity: RulesetIdentity | None = None
    degraded_desired: Any = None
    degraded_fingerprint: str | None = None
    degraded_reason: str | None = None
    degraded_consent: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "before", deep_freeze(self.before))
        object.__setattr__(self, "desired", deep_freeze(self.desired))
        object.__setattr__(self, "degraded_desired", deep_freeze(self.degraded_desired))


@dataclass(frozen=True)
class ProtectionPlan:
    repository: RepositoryIdentity
    tool_version: str
    declaration_pin: str
    snapshot_sha: str
    operations: tuple[ProtectionOperation, ...]
    ruleset_plan: RulesetPlan
    authorization_guard: Mapping[str, Any] | None
    authority_snapshot: Mapping[str, Any]
    blockers: tuple[str, ...]
    canonical_json: str
    plan_id: str
    allow_degraded_tag_pattern: bool = False
    receipt_signing_identity: Mapping[str, str] | None = None

    @property
    def ready(self) -> bool:
        return not self.blockers and all(operation.disposition == "ready" for operation in self.operations)


@dataclass(frozen=True)
class ReceiptOperation:
    identity: str
    kind: str
    status: OperationStatus
    detail: str = ""


@dataclass(frozen=True)
class ProtectionReceipt:
    plan_id: str
    status: Literal["ready", "failed", "indeterminate", "blocked"]
    operations: tuple[ReceiptOperation, ...]
    rulesets: tuple[Mapping[str, Any], ...]
    final_fingerprint: str
    timestamp: int
    persistence_status: str = "not-requested"
    local_mutations_recorded: bool = False
    repository: RepositoryIdentity | None = None
    declaration_pin: str = ""
    snapshot_sha: str = ""
    tool_version: str = ""
    authority_snapshot: Mapping[str, Any] = field(default_factory=dict)
    confirmed_plan_id: str = ""
    final_plan_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rulesets", tuple(deep_freeze(item) for item in self.rulesets))
        object.__setattr__(self, "authority_snapshot", deep_freeze(self.authority_snapshot))

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.persistence_status == "attached"

    @property
    def auto_retirement_authorized(self) -> bool:
        return self.ready and self.persistence_status == "attached"

    @property
    def canonical_bytes(self) -> bytes:
        return _json(
            {
                "schema": "aviato-protection-receipt/v1",
                "plan_id": self.plan_id,
                "status": self.status,
                "operations": [_plain(item) for item in self.operations],
                "rulesets": [_plain(item) for item in self.rulesets],
                "final_fingerprint": self.final_fingerprint,
                "timestamp": self.timestamp,
                "persistence_status": self.persistence_status,
                "local_mutations_recorded": self.local_mutations_recorded,
                "repository": _plain(self.repository),
                "declaration_pin": self.declaration_pin,
                "snapshot_sha": self.snapshot_sha,
                "tool_version": self.tool_version,
                "authority_snapshot": _plain(self.authority_snapshot),
                "confirmed_plan_id": self.confirmed_plan_id,
                "final_plan_id": self.final_plan_id,
            }
        ).encode("ascii")


@dataclass(frozen=True)
class ReceiptPersistenceEvidence:
    envelope: bytes
    issue_node_id: str
    comment_node_id: str
    source_comment_node_id: str
    comment_database_id: int
    author: str
    author_database_id: int
    author_is_admin: bool
    key_id: str
    key_current: bool
    created_at: str
    last_edited_at: str | None
    is_minimized: bool


def receipt_persistence_ready(evidence: ReceiptPersistenceEvidence) -> bool:
    return bool(
        evidence.envelope
        and evidence.issue_node_id
        and evidence.comment_node_id
        and evidence.source_comment_node_id == evidence.comment_node_id
        and evidence.comment_database_id > 0
        and evidence.author
        and evidence.author_database_id > 0
        and evidence.author_is_admin
        and evidence.key_id
        and evidence.key_current
        and evidence.created_at
        and evidence.last_edited_at is None
        and not evidence.is_minimized
    )


def sign_protection_receipt(
    canonical_receipt: bytes,
    *,
    principal: str,
    key_id: str,
    signer: Callable[[bytes], bytes],
) -> bytes:
    if not canonical_receipt or not principal or not key_id:
        raise ValueError("receipt signature requires canonical bytes, a principal, and a key id")
    try:
        receipt = json.loads(canonical_receipt)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt bytes are not canonical JSON") from exc
    if canonical_receipt != _json(receipt).encode("ascii"):
        raise ValueError("receipt bytes are not exact canonical JSON")
    signature = signer(canonical_receipt)
    if not signature:
        raise ValueError("receipt signer returned an empty signature")
    return _json(
        {
            "schema": "aviato-protection-receipt-envelope/v1",
            "principal": principal,
            "key_id": key_id,
            "algorithm": "ssh-ed25519",
            "receipt_base64url": base64.urlsafe_b64encode(canonical_receipt).decode("ascii").rstrip("="),
            "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
        }
    ).encode("ascii")


def verify_protection_receipt_envelope(
    envelope: bytes,
    *,
    expected_receipt: bytes,
    expected_principal: str,
    expected_key_id: str,
    verify_signature: Callable[[bytes, bytes], bool],
) -> bytes:
    try:
        document = json.loads(envelope)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt envelope is not JSON") from exc
    fields = {"schema", "principal", "key_id", "algorithm", "receipt_base64url", "signature"}
    if not isinstance(document, dict) or set(document) != fields or envelope != _json(document).encode("ascii"):
        raise ValueError("receipt envelope is not exact canonical JSON")
    if (
        document["schema"] != "aviato-protection-receipt-envelope/v1"
        or document["algorithm"] != "ssh-ed25519"
        or document["principal"] != expected_principal
        or document["key_id"] != expected_key_id
    ):
        raise ValueError("receipt signature identity differs from the preview-bound authority")
    try:
        receipt = base64.b64decode(
            str(document["receipt_base64url"]) + "=" * (-len(str(document["receipt_base64url"])) % 4),
            altchars=b"-_",
            validate=True,
        )
        signature = base64.b64decode(
            str(document["signature"]) + "=" * (-len(str(document["signature"])) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise ValueError("receipt envelope contains malformed base64url") from exc
    if receipt != expected_receipt or not signature or verify_signature(receipt, signature) is not True:
        raise ValueError("receipt bytes or SSH signature failed exact verification")
    return receipt


@dataclass(frozen=True)
class ProtectionExecutionResult:
    receipt: ProtectionReceipt


class ResponseLostError(RuntimeError):
    """The platform may have accepted the write but its response was lost."""


def _plain(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items()}
    return value


def canonical_authority_snapshot(*, repository: RepositoryIdentity, live_state: Mapping[str, Any]) -> Mapping[str, Any]:
    plain = _plain(live_state)
    required_checks = live_state.get("required_checks")
    if not isinstance(required_checks, (list, tuple)):
        checks = live_state.get("checks", {})
        required_checks = [
            {"context": str(name), "app_id": None, "integration_id": None, "source": "normalized"}
            for name in sorted(checks if isinstance(checks, Mapping) else ())
        ]
    plain["required_checks"] = [_plain(item) for item in required_checks if isinstance(item, Mapping)]
    snapshot = project_authority_snapshot(_plain(repository), plain)
    return cast(Mapping[str, Any], deep_freeze(snapshot))


def authority_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    if snapshot.get("schema") != AUTHORITY_SNAPSHOT_SCHEMA:
        raise ValueError("authority snapshot schema is absent or unsupported")
    return _digest(_plain(snapshot))


def _operation(
    kind: str, name: str, before: object, desired: object, *, disposition: SurfaceStatus = "ready", detail: str = ""
) -> ProtectionOperation:
    before_plain, desired_plain = _plain(before), _plain(desired)
    return ProtectionOperation(
        f"{kind}:{name}",
        kind,
        name,
        "noop" if before_plain == desired_plain else "update",
        before_plain,
        desired_plain,
        _digest(before_plain),
        _digest(desired_plain),
        disposition,
        detail,
    )


def build_protection_plan(
    *,
    repository: RepositoryIdentity,
    tool_version: str,
    declaration_pin: str,
    snapshot_sha: str,
    desired_state: object,
    desired_rulesets: Sequence[Mapping[str, Any]],
    live_state: Mapping[str, Any],
    environments: Sequence[ProtectedEnvironment] = (),
    allow_degraded_tag_pattern: bool = False,
    receipt_signing_identity: Mapping[str, str] | None = None,
) -> ProtectionPlan:
    live_repository = live_state.get("repository_identity")
    blockers: list[str] = []
    if live_repository != repository:
        blockers.append("repository identity/default branch changed or is unreadable")
    settings = _plain(getattr(desired_state, "settings", {}))
    default_branch = settings.get("default_branch", {}) if isinstance(settings, dict) else {}
    all_repository_settings = settings.get("repository", {}) if isinstance(settings, dict) else {}
    repository_settings = {key: value for key, value in all_repository_settings.items() if "merge" not in key}
    security_settings = settings.get("security", {}) if isinstance(settings, dict) else {}
    merge_settings = {key: value for key, value in all_repository_settings.items() if "merge" in key}
    operations = [
        _operation("classic", "default-branch", live_state.get("classic", {}), default_branch),
        _operation("repository", "repository", live_state.get("repository", {}), repository_settings),
        _operation("security", "security", live_state.get("security", {}), security_settings),
        _operation("merge", "merge", live_state.get("merge", {}), merge_settings),
    ]
    ruleset_plan = build_ruleset_plan(
        repository=repository,
        tool_version=tool_version,
        declaration_pin=declaration_pin,
        snapshot_sha=snapshot_sha,
        desired_payloads=desired_rulesets,
        live_payloads=live_state.get("rulesets", ()),
    )
    for rule in ruleset_plan.operations:
        desired_payload = deep_thaw(rule.desired_payload) if rule.desired_payload else None
        degraded_payload = None
        degraded_fingerprint = None
        degraded_reason = None
        if isinstance(desired_payload, dict) and desired_payload.get("target") == "tag":
            rules = desired_payload.get("rules")
            if isinstance(rules, list):
                retained = [
                    item for item in rules if not (isinstance(item, Mapping) and item.get("type") == "tag_name_pattern")
                ]
                if len(retained) != len(rules):
                    degraded_payload = {**desired_payload, "rules": retained}
                    degraded_fingerprint = _digest(degraded_payload)
                    degraded_reason = "github-unsupported-tag_name_pattern-422"
        operations.append(
            ProtectionOperation(
                f"ruleset:{rule.identity.name}:{rule.identity.target}",
                "ruleset",
                rule.identity.name,
                rule.action,
                rule.before_fingerprint,
                desired_payload,
                rule.before_fingerprint or _digest(None),
                rule.desired_fingerprint or _digest(None),
                rule.disposition,
                rule.reason,
                rule.identity,
                degraded_payload,
                degraded_fingerprint,
                degraded_reason,
                bool(allow_degraded_tag_pattern and degraded_payload is not None),
            )
        )
        if rule.disposition != "ready":
            blockers.append(f"ruleset {rule.identity.name}: {rule.reason or rule.disposition}")
    live_environments = live_state.get("environments", {})
    for environment in environments:
        desired_environment = deep_thaw(environment.payload())
        before = live_environments.get(environment.name, {}) if isinstance(live_environments, Mapping) else {}
        disposition: SurfaceStatus = "ready"
        detail = ""
        if not environment.reviewers:
            disposition, detail = "manual", f"environment {environment.name} has no resolved reviewer identity"
        elif not environment.forbid_admin_bypass:
            disposition, detail = "manual", f"environment {environment.name} requires --forbid-admin-bypass"
        elif not isinstance(before, Mapping) or before.get("can_admins_bypass") is not False:
            disposition, detail = "manual", f"environment {environment.name} requires manual can_admins_bypass=false"
        elif environment.custom_rules or before.get("custom_rules"):
            disposition, detail = (
                "manual",
                f"environment {environment.name} custom protection rules are unsupported "
                "and require manual convergence",
            )
        operations.append(
            _operation(
                "environment", environment.name, before, desired_environment, disposition=disposition, detail=detail
            )
        )
        if disposition != "ready":
            blockers.append(detail)
    checks = {name: "success" for name in getattr(desired_state, "required_status_checks", ())}
    operations.append(_operation("checks", "required", live_state.get("checks", {}), checks))
    guard = _plain(getattr(desired_state, "authorization_guard", None))
    if environments and not guard:
        blockers.append("privileged environments require an independent managed authorization guard")
    elif guard and _plain(live_state.get("guard")) != guard:
        blockers.append("managed authorization guard workflow/path/blob is not proven live")
    release_guard = live_state.get("release_guard")
    if environments and (
        not isinstance(release_guard, Mapping)
        or release_guard.get("path") != ".github/workflows/reusable-release.yml"
        or not isinstance(release_guard.get("repository"), str)
        or not isinstance(release_guard.get("ref"), str)
        or not isinstance(release_guard.get("blob_sha"), str)
        or len(release_guard["blob_sha"]) != 40
    ):
        blockers.append("reusable release repository/ref/blob is not proven live")
    verifier_guard = live_state.get("verifier_guard")
    if environments and (
        not isinstance(verifier_guard, Mapping)
        or verifier_guard.get("path") != "aviato/authority_verifier.py"
        or not isinstance(verifier_guard.get("blob_sha"), str)
        or len(verifier_guard["blob_sha"]) != 40
    ):
        blockers.append("shared authority verifier repository/ref/blob is not proven live")
    authority_snapshot = canonical_authority_snapshot(repository=repository, live_state=live_state)
    payload = {
        "repository": _plain(repository),
        "tool_version": tool_version,
        "declaration_pin": declaration_pin,
        "snapshot_sha": snapshot_sha,
        "operations": [_plain(item) for item in operations],
        "ruleset_plan_id": ruleset_plan.plan_id,
        "authorization_guard": guard,
        "authority_snapshot": _plain(authority_snapshot),
        "allow_degraded_tag_pattern": allow_degraded_tag_pattern,
        "receipt_signing_identity": _plain(receipt_signing_identity),
        "blockers": blockers,
    }
    canonical = _json(payload)
    return ProtectionPlan(
        repository=repository,
        tool_version=tool_version,
        declaration_pin=declaration_pin,
        snapshot_sha=snapshot_sha,
        operations=tuple(operations),
        ruleset_plan=ruleset_plan,
        authorization_guard=deep_freeze(guard) if guard else None,
        authority_snapshot=authority_snapshot,
        blockers=tuple(blockers),
        canonical_json=canonical,
        plan_id=hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        allow_degraded_tag_pattern=allow_degraded_tag_pattern,
        receipt_signing_identity=deep_freeze(receipt_signing_identity) if receipt_signing_identity else None,
    )


def require_protection_confirmation(
    plan: ProtectionPlan, *, apply: bool, confirmation: str | None
) -> ProtectionPlan | None:
    if not apply:
        return None
    if confirmation != plan.plan_id:
        raise ValueError(f"complete protection requires exact --confirm {plan.plan_id}")
    if not plan.ready:
        raise ValueError(f"protection plan is not ready: {list(plan.blockers)}")
    return plan


def verify_protection_recheck(
    original: ProtectionPlan,
    current: ProtectionPlan,
    *,
    completed: frozenset[str],
    bound_ruleset_identities: Mapping[str, RulesetIdentity] | None = None,
) -> None:
    if (
        original.repository != current.repository
        or original.declaration_pin != current.declaration_pin
        or original.snapshot_sha != current.snapshot_sha
        or original.blockers != current.blockers
    ):
        raise ValueError("protection plan changed after confirmation")
    original_ops = {item.identity: item for item in original.operations}
    current_ops = {item.identity: item for item in current.operations}
    if set(original_ops) != set(current_ops):
        raise ValueError("protection plan changed after confirmation")
    for identity, operation in original_ops.items():
        candidate = current_ops[identity]
        if identity in completed:
            expected_ruleset_identity = (bound_ruleset_identities or {}).get(identity, operation.ruleset_identity)
            if (
                candidate.action != "noop"
                or candidate.desired_fingerprint != operation.desired_fingerprint
                or candidate.ruleset_identity != expected_ruleset_identity
            ):
                raise ValueError("completed protection surface drifted after write")
        elif candidate != operation and not (
            candidate.action == "noop"
            and candidate.desired_fingerprint == operation.desired_fingerprint
            and (operation.ruleset_identity is None or candidate.ruleset_identity == operation.ruleset_identity)
        ):
            raise ValueError("protection plan changed after confirmation")


def plan_with_operation_converged(plan: ProtectionPlan, identity: str) -> ProtectionPlan:
    operations = tuple(
        replace(item, action="noop", before=item.desired, before_fingerprint=item.desired_fingerprint)
        if item.identity == identity
        else item
        for item in plan.operations
    )
    return replace(plan, operations=operations)


def protection_state_fingerprint(plan: ProtectionPlan) -> str:
    """Fingerprint only the final live semantic state, not the pre-write plan."""
    return authority_snapshot_digest(plan.authority_snapshot)


def receipt_for_plan(
    plan: ProtectionPlan,
    *,
    confirmed_plan: ProtectionPlan | None = None,
    status: Literal["ready", "failed", "indeterminate", "blocked"],
    operations: Sequence[ReceiptOperation] = (),
    persistence_status: str = "not-requested",
) -> ProtectionReceipt:
    confirmed = confirmed_plan or plan
    rulesets = tuple(
        deep_freeze(
            {
                "id": item.identity.live_id,
                "name": item.identity.name,
                "target": item.identity.target,
                "fingerprint": item.desired_fingerprint,
            }
        )
        for item in plan.ruleset_plan.operations
    )
    return ProtectionReceipt(
        confirmed.plan_id,
        status,
        tuple(operations),
        rulesets,
        protection_state_fingerprint(plan),
        int(time.time()),
        persistence_status,
        bool(operations) or status == "ready",
        plan.repository,
        plan.declaration_pin,
        plan.snapshot_sha,
        plan.tool_version,
        plan.authority_snapshot,
        confirmed.plan_id,
        plan.plan_id,
    )


def execute_protection_plan(
    plan: ProtectionPlan,
    *,
    confirmation: str,
    recompute: Callable[[], ProtectionPlan],
    write: Callable[[ProtectionOperation], object],
    authorize: Callable[[], None],
    persist_receipt: Callable[[bytes], ReceiptPersistenceEvidence] | None = None,
) -> ProtectionExecutionResult:
    try:
        require_protection_confirmation(plan, apply=True, confirmation=confirmation)
    except ValueError:
        return ProtectionExecutionResult(receipt_for_plan(plan, status="blocked"))
    attempted: list[ReceiptOperation] = []
    completed: set[str] = set()
    bound_ruleset_identities: dict[str, RulesetIdentity] = {}
    pending = [item for item in plan.operations if item.action != "noop"]
    try:
        verify_protection_recheck(plan, recompute(), completed=frozenset())
    except Exception as exc:
        attempted.append(ReceiptOperation("preflight", "barrier", "indeterminate", str(exc)))
        return ProtectionExecutionResult(receipt_for_plan(plan, status="indeterminate", operations=attempted))
    failure_status: Literal["failed", "indeterminate"] | None = None
    for operation in pending:
        try:
            before = recompute()
            verify_protection_recheck(
                plan,
                before,
                completed=frozenset(completed),
                bound_ruleset_identities=bound_ruleset_identities,
            )
            current_operation = next(item for item in before.operations if item.identity == operation.identity)
            if current_operation.action == "noop":
                completed.add(operation.identity)
                attempted.append(
                    ReceiptOperation(
                        operation.identity,
                        operation.kind,
                        "completed",
                        "converged by an earlier correlated write",
                    )
                )
                continue
        except Exception as exc:
            attempted.append(ReceiptOperation(operation.identity, operation.kind, "indeterminate", str(exc)))
            failure_status = "indeterminate"
            break
        lost = False
        write_result: object | None = None
        try:
            # Reverify the external signed/live authority after the operation's
            # state recheck and immediately before this exact mutation.
            authorize()
            write_result = write(current_operation)
        except ResponseLostError:
            lost = True
        except Exception as exc:
            attempted.append(ReceiptOperation(operation.identity, operation.kind, "failed", str(exc)))
            failure_status = "failed"
            break
        if getattr(write_result, "degraded_rules", ()):
            attempted.append(
                ReceiptOperation(
                    operation.identity,
                    operation.kind,
                    "failed",
                    "explicitly consented degraded tag-pattern variant applied; protection remains non-ready",
                )
            )
            failure_status = "failed"
            break
        try:
            after = recompute()
            candidate = next(item for item in after.operations if item.identity == operation.identity)
        except Exception as exc:
            attempted.append(ReceiptOperation(operation.identity, operation.kind, "indeterminate", str(exc)))
            failure_status = "indeterminate"
            break
        if candidate.action != "noop":
            detail = "lost response did not read back desired state" if lost else "post-write readback did not converge"
            attempted.append(ReceiptOperation(operation.identity, operation.kind, "indeterminate", detail))
            failure_status = "indeterminate"
            break
        if operation.ruleset_identity is not None:
            confirmed_identity = operation.ruleset_identity
            actual_identity = candidate.ruleset_identity
            if actual_identity is None:
                attempted.append(
                    ReceiptOperation(operation.identity, operation.kind, "indeterminate", "ruleset identity missing")
                )
                failure_status = "indeterminate"
                break
            if confirmed_identity.live_id is None:
                if actual_identity.live_id is None or actual_identity.key != confirmed_identity.key:
                    attempted.append(
                        ReceiptOperation(
                            operation.identity,
                            operation.kind,
                            "indeterminate",
                            "created ruleset did not bind one exact returned live identity",
                        )
                    )
                    failure_status = "indeterminate"
                    break
                bound_ruleset_identities[operation.identity] = actual_identity
            elif actual_identity != confirmed_identity:
                attempted.append(
                    ReceiptOperation(
                        operation.identity,
                        operation.kind,
                        "indeterminate",
                        "confirmed ruleset identity was replaced after write",
                    )
                )
                failure_status = "indeterminate"
                break
            else:
                bound_ruleset_identities[operation.identity] = confirmed_identity
        completed.add(operation.identity)
        attempted.append(ReceiptOperation(operation.identity, operation.kind, "completed", "readback converged"))
    if failure_status:
        attempted.extend(
            ReceiptOperation(item.identity, item.kind, "unattempted", "earlier operation did not converge")
            for item in pending[len(attempted) :]
        )
        return ProtectionExecutionResult(receipt_for_plan(plan, status=failure_status, operations=attempted))
    try:
        final = recompute()
        verify_protection_recheck(
            plan,
            final,
            completed=frozenset(item.identity for item in pending),
            bound_ruleset_identities=bound_ruleset_identities,
        )
        if any(item.action != "noop" for item in final.operations):
            raise ValueError("final convergence barrier is not clean")
    except Exception as exc:
        attempted.append(ReceiptOperation("final-barrier", "barrier", "indeterminate", str(exc)))
        return ProtectionExecutionResult(receipt_for_plan(plan, status="indeterminate", operations=attempted))
    receipt = receipt_for_plan(
        final,
        confirmed_plan=plan,
        status="ready",
        operations=attempted,
        persistence_status="not-requested" if persist_receipt is None else "attached",
    )
    if persist_receipt is not None:
        try:
            # Durable persistence is itself a hosted mutation and therefore
            # receives its own fresh authority decision.
            authorize()
            evidence = persist_receipt(receipt.canonical_bytes)
            if not isinstance(evidence, ReceiptPersistenceEvidence) or not receipt_persistence_ready(evidence):
                raise ValueError("receipt persistence did not return immutable current-authority evidence")
        except Exception:
            receipt = replace(receipt, persistence_status="failed")
    return ProtectionExecutionResult(receipt)
