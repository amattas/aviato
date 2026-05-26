"""GitHub binding for the agnostic :class:`aviato.core.ports.Platform` (§2.14).

This is the day-zero hosting-platform binding. It lives outside ``aviato.core``
(the core depends only on the Protocol) and composes the gh-backed helpers in
:mod:`aviato.github`. The reporting/read methods are low-privilege; the only
mutating method, ``apply_settings``, is reached solely through the §5.7 gated
path. Live behavior is operator-verified (§9.2/§8.10); the response-mapping
logic below is unit-tested.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import github
from .command import CommandError
from .core.consent import ACTOR_HUMAN, ROLE_PRIVILEGED
from .core.ports import Issue
from .core.settingsdrift import CONSENT_ID_HEX_LEN

# A human grants consent by adding a label of this form to the tracking issue;
# the diff identity it authorizes is encoded after the prefix (§6.4).
CONSENT_LABEL_PREFIX = "aviato-consent:"

# GitHub rejects label names longer than 50 characters. The consent-grant label is
# CONSENT_LABEL_PREFIX + diff_identity(...), and a human must be able to create it for the
# §5.7 reconcile gate to function — so the prefixed id MUST fit. Guard the invariant at import
# time so a future change to either the prefix or the id length fails loud here rather than
# silently making the gate unreachable (no test exercises the live label round-trip).
GITHUB_LABEL_NAME_MAX = 50
if len(CONSENT_LABEL_PREFIX) + CONSENT_ID_HEX_LEN > GITHUB_LABEL_NAME_MAX:
    # An explicit raise (not assert) so the guard holds even under `python -O`.
    raise RuntimeError(
        f"consent label {CONSENT_LABEL_PREFIX!r}+{CONSENT_ID_HEX_LEN}-char id exceeds "
        f"GitHub's {GITHUB_LABEL_NAME_MAX}-char label limit; the §5.7 reconcile gate "
        "would be unreachable"
    )


def _select_issue(issues: Any, repo: str, key: str) -> dict[str, Any] | None:
    """Pick the one tracking issue for ``key`` from a labels-filtered list, deterministically.

    Exactly one issue should ever carry the consent/drift label. If more than one does
    (a prior duplicate from a flaky run, or a human-opened lookalike), the three reads
    (open-list / all-list) must agree on WHICH issue — otherwise consent could be read on one
    and audited on another. Prefer an **open** issue (the actionable one), and among the chosen
    state pick the oldest (lowest number); only fall back to a closed issue when none are open.
    Preferring open keeps the all-state read (get_issue/comment_issue) agreeing with the
    open-only read (open_or_update_issue) whenever an open issue exists, and stops a stale
    *closed* duplicate from shadowing a live open issue (which would wrongly refuse reconcile).
    Warn loudly on duplicates (§5.6). Returns the chosen issue dict, or ``None`` if the list is
    empty/malformed.
    """
    if not isinstance(issues, list) or not issues:
        return None
    numbered = [i for i in issues if isinstance(i, dict) and isinstance(i.get("number"), int)]
    if not numbered:
        # No usable "number" — fall back to the first dict so callers can still create afresh.
        return next((i for i in issues if isinstance(i, dict)), None)
    # Prefer open issues; fall back to the full set only when none are open.
    pool = [i for i in numbered if i.get("state") == "open"] or numbered
    if len(pool) > 1:
        print(
            f"WARNING: {repo} has multiple issues labeled {key!r}; acting on the oldest "
            f"(#{min(n['number'] for n in pool)}). Close the duplicates to restore a clean "
            "consent/audit trail (§5.6).",
            file=sys.stderr,
        )
    return min(pool, key=lambda i: i["number"])


def _seg(value: str) -> str:
    """Percent-encode a single-token value spliced into a ``gh api`` path/query.

    Calls go through ``gh api`` argv (no shell), so this is not about shell injection
    — it prevents a value containing ``/`` or ``?`` from altering the API path or
    query. ``safe=""`` because these are single segments (a label name, a login),
    never multi-segment paths like ``OWNER/REPO``.
    """
    return quote(str(value), safe="")


class UnmodeledProtectionError(RuntimeError):
    """Raised when a settings apply would drop live protections the model doesn't cover."""


def _is_feature_unavailable(exc: CommandError) -> bool:
    """True if a gh error reports a security feature is unavailable for the repo (§17).

    These (secret scanning, push protection, Dependabot security updates) require the
    relevant features enabled at the org/repo level — an adoption prerequisite, not an
    apply failure.

    Tightened to require an availability phrase **in a security-feature context** (or the
    unambiguous "advanced security"), so an unrelated error that merely contains the words
    "not enabled" is NOT misclassified as a benign adoption warning and is allowed to raise.
    """
    msg = exc.stderr.lower()
    if "advanced security" in msg:
        return True
    availability = "not available" in msg or "not enabled" in msg or "must be enabled" in msg
    feature_context = "security" in msg or "scanning" in msg or "dependabot" in msg
    return availability and feature_context


@dataclass(frozen=True)
class ConsentGrant:
    diff_id: str
    actor_type: str | None
    actor_login: str | None


def _chronological(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable-sort timeline entries by ``created_at`` (R2-1/§2.8/§6.4).

    The issue-timeline API + ``--slurp`` page concatenation do NOT guarantee the array is in
    strict chronological order, so a revoke returned BEFORE its stale grant (or a post-grant
    non-human edit returned before the grant) would be mis-reduced and a revoked consent could
    re-authorize an apply. Sorting by the event timestamp makes the grant/revoke reduction reflect
    true history, not array position. ISO-8601 timestamps sort lexically; the original index is the
    tiebreak (stable). Entries lacking ``created_at`` (e.g. synthetic test events) keep their
    relative order via the index tiebreak.
    """
    return [e for _, e in sorted(enumerate(timeline), key=lambda pair: (str(pair[1].get("created_at") or ""), pair[0]))]


def _label_events(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize GitHub timeline entries into label-event dicts for :func:`current_consent`.

    Carries ``created_at`` so :func:`current_consent` can reduce by true chronology (R2-1)."""
    events: list[dict[str, Any]] = []
    for entry in timeline:
        action = entry.get("event")
        if action not in ("labeled", "unlabeled"):
            continue
        label = entry.get("label") or {}
        actor = entry.get("actor") or {}
        events.append(
            {
                "action": action,
                "label": label.get("name", ""),
                "actor_type": actor.get("type"),
                "actor_login": actor.get("login"),
                "created_at": entry.get("created_at"),
            }
        )
    return events


def nonhuman_edit_after_grant(timeline: list[dict[str, Any]], diff_id: str) -> bool:
    """True if a non-human actor touched the issue after the consent grant (§2.8/§5.7).

    Finds the latest grant of ``aviato-consent:<diff_id>`` and reports whether any
    later timeline entry was performed by an actor whose type is not ``User`` (a
    Bot/App/unknown actor). Entries with no actor are system events and ignored.
    "Later" is by ``created_at`` chronology, not array position (R2-1).
    """
    timeline = _chronological(timeline)
    grant_label = f"{CONSENT_LABEL_PREFIX}{diff_id}"
    grant_index = -1
    for i, entry in enumerate(timeline):
        if entry.get("event") == "labeled" and (entry.get("label") or {}).get("name") == grant_label:
            grant_index = i
    if grant_index < 0:
        return False
    for entry in timeline[grant_index + 1 :]:
        actor = entry.get("actor")
        # Fail closed (§2.7): an actor present on a post-grant edit whose type is
        # not exactly "User" — including an ambiguous/unknown type — counts as a
        # non-human edit and voids consent. Actorless system events are ignored.
        if isinstance(actor, dict) and actor.get("type") != "User":
            return True
    return False


def current_consent(events: list[dict[str, Any]]) -> ConsentGrant | None:
    """Reduce label events to the active consent grant (§6.4), in TRUE chronological order.

    Each event is ``{"action": "labeled"|"unlabeled", "label": str, "actor_type": str|None,
    "actor_login": str|None, "created_at": str|None}``. A ``labeled`` event with the consent
    prefix is a grant; a matching ``unlabeled`` is a revoke. The current consent is the most
    recent (by ``created_at``, R2-1) grant not later revoked. Reading the full (paginated) history
    is what prevents a later revoke from being missed; sorting prevents array-order mis-reduction.
    """
    active: dict[str, tuple[int, str | None, str | None]] = {}
    for seq, event in enumerate(_chronological(events)):
        label = event.get("label", "")
        if not isinstance(label, str) or not label.startswith(CONSENT_LABEL_PREFIX):
            continue
        diff_id = label[len(CONSENT_LABEL_PREFIX) :]
        if event.get("action") == "labeled":
            active[diff_id] = (seq, event.get("actor_type"), event.get("actor_login"))
        elif event.get("action") == "unlabeled":
            active.pop(diff_id, None)
    if not active:
        return None
    diff_id, (_, actor_type, actor_login) = max(active.items(), key=lambda item: item[1][0])
    return ConsentGrant(diff_id=diff_id, actor_type=actor_type, actor_login=actor_login)


# Branch-ruleset rule types the desired settings model represents (§5.6). A live
# rule of any OTHER type is unmodeled protection the reconcile must not silently
# shadow (see apply_settings fail-closed guard).
_MODELED_RULE_TYPES = frozenset({"pull_request", "non_fast_forward", "deletion", "required_status_checks"})

# Classic-protection toggles the wholesale branch-protection PUT (to_branch_protection_payload)
# does NOT carry, so if any is ENABLED live it would be silently dropped (§2.4/§2.9). Each is a
# ``{"enabled": bool}`` object on the protection GET; we fail closed when enabled rather than drop.
_UNMODELED_CLASSIC_FLAGS = (
    "required_linear_history",
    "lock_branch",
    "block_creations",
    "allow_fork_syncing",
    "required_signatures",
)
# Review sub-fields the PUT rebuilds without (it hardcodes require_code_owner_reviews=False and
# omits the rest), so an enabled one live would be dropped — fail closed (§2.4/§2.9).
_UNMODELED_REVIEW_FIELDS = (
    "require_code_owner_reviews",
    "require_last_push_approval",
    "dismissal_restrictions",
    "bypass_pull_request_allowances",
)

# The flat desired keys that describe branch protection (vs the repo security toggles,
# which live on a different API surface). Used to decide whether a desired change lands
# on the classic-protection surface or the ruleset surface.
_BRANCH_PROTECTION_KEYS = (
    "requires_pull_request",
    "required_reviews",
    "dismiss_stale_reviews",
    "require_thread_resolution",
    "enforce_admins",
    "block_force_push",
    "block_deletion",
    "required_status_checks",
)


def _norm_setting(key: str, value: Any) -> Any:
    """Normalize a flat setting value for comparison (status-check lists are order-insensitive)."""
    if key == "required_status_checks" and isinstance(value, (list, tuple, set)):
        return sorted({str(item) for item in value})
    return value


def map_branch_settings(rules: list[dict[str, Any]], protection: dict[str, Any]) -> dict[str, Any]:
    """Map live default-branch rules/protection into the flat comparable settings map (§5.6, §2.9).

    Read-shaped platform data is reduced to exactly the keys the desired baseline
    uses (so a compliant repo compares clean), never replayed verbatim into a
    write. Returns the same flat shape the resolved ``default_branch`` map carries.
    """
    pr_rule = next((r for r in rules if r.get("type") == "pull_request"), None)
    pr_params = pr_rule.get("parameters", {}) if pr_rule else {}
    classic_reviews = protection.get("required_pull_request_reviews") or {}
    requires_pr = pr_rule is not None or protection.get("required_pull_request_reviews") is not None

    if pr_rule is not None:
        required_reviews = int(pr_params.get("required_approving_review_count", 0))
        dismiss_stale = bool(pr_params.get("dismiss_stale_reviews_on_push", False))
        require_threads = bool(pr_params.get("required_review_thread_resolution", False))
    else:
        required_reviews = int(classic_reviews.get("required_approving_review_count", 0))
        dismiss_stale = bool(classic_reviews.get("dismiss_stale_reviews", False))
        require_threads = bool((protection.get("required_conversation_resolution") or {}).get("enabled", False))

    rules_nff = any(r.get("type") == "non_fast_forward" for r in rules)
    allow_force = protection.get("allow_force_pushes")
    classic_force_blocked = isinstance(allow_force, dict) and allow_force.get("enabled") is not True
    block_force_push = rules_nff or classic_force_blocked

    rules_deletion = any(r.get("type") == "deletion" for r in rules)
    allow_del = protection.get("allow_deletions")
    classic_deletion_blocked = isinstance(allow_del, dict) and allow_del.get("enabled") is not True
    block_deletion = rules_deletion or classic_deletion_blocked

    # Status checks can be enforced by EITHER classic branch protection OR a branch
    # ruleset's required_status_checks rule (the bundled "protect default branch"
    # ruleset uses the latter). Read both, or a rule-protected repo maps to an empty
    # set and shows false drift / a duplicate classic-protection write (§5.6).
    rsc = protection.get("required_status_checks") or {}
    contexts = list(rsc.get("contexts") or [])
    contexts += [c.get("context") for c in rsc.get("checks", []) if isinstance(c, dict) and c.get("context")]
    rsc_rule = next((r for r in rules if r.get("type") == "required_status_checks"), None)
    if rsc_rule is not None:
        rule_checks = rsc_rule.get("parameters", {}).get("required_status_checks", [])
        contexts += [c.get("context") for c in rule_checks if isinstance(c, dict) and c.get("context")]

    # enforce_admins = "are admins subject to branch protection?". It's satisfied EITHER by the
    # classic toggle ({"enabled": true}) OR by a branch RULESET owning protection — a ruleset
    # enforces on everyone, including admins, absent a bypass actor (the Aviato baseline ruleset
    # has none). Reading it both ways keeps it in the §5.7 diff (§2.9 — never silently forced)
    # WITHOUT false-drifting/locking out the normal ruleset-protected repo, where classic
    # protection is empty (its rules live on the ruleset). A classic-only repo reads the toggle.
    # A protecting ruleset enforces on admins unless it grants a bypass actor — and an added
    # bypass IS detected as ruleset content drift (rulesets.ruleset_content_drift, the §5.6 path),
    # so treating a ruleset-owned branch as enforce_admins-satisfied here does not hide a bypass.
    classic_enforce_admins = bool((protection.get("enforce_admins") or {}).get("enabled", False))
    ruleset_owns_branch = any(rule.get("type") in _MODELED_RULE_TYPES for rule in rules)
    enforce_admins = classic_enforce_admins or ruleset_owns_branch

    return {
        "requires_pull_request": requires_pr,
        "required_reviews": required_reviews,
        "dismiss_stale_reviews": dismiss_stale,
        "require_thread_resolution": require_threads,
        "block_force_push": block_force_push,
        "block_deletion": block_deletion,
        "enforce_admins": enforce_admins,
        "required_status_checks": sorted(set(contexts)),
    }


def map_security_settings(security_and_analysis: dict[str, Any]) -> dict[str, Any]:
    """Map the live ``security_and_analysis`` block to the flat security settings (§2.13).

    Only the toggles GitHub actually reports are returned; an undeterminable one is
    omitted (so it shows as additive "to enable", never a false destructive). Code
    scanning is delivered by the CodeQL **workflow** (a managed artifact, covered by
    file drift), so it is not read here as a repo toggle.
    """
    out: dict[str, Any] = {}

    def _enabled(key: str) -> bool:
        value = security_and_analysis.get(key)
        return isinstance(value, dict) and value.get("status") == "enabled"

    if "secret_scanning" in security_and_analysis:
        out["secret_scanning"] = _enabled("secret_scanning")
    if "secret_scanning_push_protection" in security_and_analysis:
        out["secret_push_protection"] = _enabled("secret_scanning_push_protection")
    if "dependabot_security_updates" in security_and_analysis:
        out["dependency_scanning"] = _enabled("dependabot_security_updates")
    return out


# The flat repo-security toggle keys this binding reconciles (the to_security_payload mapping
# keys). Combined with _BRANCH_PROTECTION_KEYS below into RECONCILABLE_SETTING_KEYS — the full
# set of desired keys the apply path actually writes. A desired key OUTSIDE this set would be
# silently ignored by the writers (phantom drift that "applies" but never converges), so callers
# filter to it and `aviato validate` asserts the baseline declares only recognized keys (§5.1).
_SECURITY_SETTING_KEYS = ("secret_scanning", "secret_push_protection", "dependency_scanning")


def to_security_payload(desired: dict[str, Any]) -> dict[str, Any]:
    """Build a ``security_and_analysis`` PATCH from the flat desired settings (§2.9)."""
    mapping = {
        "secret_scanning": "secret_scanning",
        "secret_push_protection": "secret_scanning_push_protection",
        "dependency_scanning": "dependabot_security_updates",
    }
    payload: dict[str, Any] = {}
    for desired_key, api_key in mapping.items():
        if desired_key in desired:
            payload[api_key] = {"status": "enabled" if desired[desired_key] else "disabled"}
    return payload


# Every flat desired key the apply path can actually write (branch protection + repo security).
# A desired key outside this set is unreconcilable: filtered out before the diff so a typo can't
# masquerade as never-converging "drift", and asserted against the baseline by `aviato validate`.
RECONCILABLE_SETTING_KEYS = frozenset(_BRANCH_PROTECTION_KEYS) | frozenset(_SECURITY_SETTING_KEYS)


def to_branch_protection_payload(desired: dict[str, Any]) -> dict[str, Any]:
    """Translate the flat desired settings into a complete branch-protection PUT payload (§2.9).

    The PUT endpoint replaces protection wholesale, so the full desired state is
    sent in the API's own shape (all required keys present, nullable where unset)
    — not the internal key names, and not a partial diff that would drop other
    protections.
    """
    reviews: dict[str, Any] | None = None
    if desired.get("requires_pull_request"):
        reviews = {
            "required_approving_review_count": int(desired.get("required_reviews", 1)),
            "dismiss_stale_reviews": bool(desired.get("dismiss_stale_reviews", False)),
            "require_code_owner_reviews": False,
        }
    # §10: require the verify/security checks to merge. None when unmodeled/empty.
    contexts = list(desired.get("required_status_checks") or [])
    status_checks = {"strict": True, "contexts": contexts} if contexts else None
    return {
        "required_status_checks": status_checks,
        # Default True (admins subject to protection), but driven by the modeled desired value
        # so the apply matches the §5.7-reviewed diff rather than blindly forcing it (§2.9).
        "enforce_admins": bool(desired.get("enforce_admins", True)),
        "required_pull_request_reviews": reviews,
        "restrictions": None,
        "allow_force_pushes": not bool(desired.get("block_force_push", False)),
        "allow_deletions": not bool(desired.get("block_deletion", False)),
        "required_conversation_resolution": bool(desired.get("require_thread_resolution", False)),
    }


class GitHubPlatform:
    """Concrete :class:`aviato.core.ports.Platform` over the ``gh``/``git`` CLIs."""

    def __init__(self, workdir: Path | str = ".") -> None:
        self.workdir = Path(workdir)

    def read_settings(self, repo: str) -> dict[str, Any]:
        # Returns the flat default-branch settings map, matching the desired map
        # the CLI passes (resolved.settings["default_branch"]) so the diff compares
        # like-for-like (§5.6).
        #
        # A read failure here (e.g. the platform token lacks the admin scope branch
        # protection/rulesets require) is raised as SettingsReadError so the caller can
        # fail closed by SKIPPING settings drift (§5.6) — distinct from an issue-channel
        # failure, which must fail loud. We never compute a diff from a falsely-
        # "unprotected" read (§2.7): the gh_* readers already fail closed on ambiguity.
        # All four reads run under the read-only admin token (§5.6/§11.2): the issue writes
        # this automation also performs (open/comment/revoke) stay on the ambient platform
        # token, so the stored admin secret is read-only IN USE and never mutates anything.
        try:
            with github.settings_read_token_scope():
                branch = github.default_branch(repo)
                if not branch:
                    # R2-3: an unresolvable default branch is ambiguous, not "unprotected" — raise
                    # (fail-closed SKIP) instead of returning {} (which would diff every desired key
                    # as additive drift, over-reporting). Mirrors apply_settings' refusal (§2.7).
                    raise github.SettingsReadError(f"repos/{repo}", 0, "could not resolve default branch")
                rules = github.active_branch_rules(repo, branch)
                protection = github.classic_branch_protection(repo, branch)
                security = map_security_settings(github.repo_security_settings(repo))
        except github.GitHubAPIError as exc:
            raise github.SettingsReadError(exc.endpoint, exc.returncode, exc.stderr) from exc
        # Flat merge: branch-protection fields + repo security toggles, matching the
        # flat desired map the CLI passes (so security drift is visible, §5.6/§2.13).
        return {**map_branch_settings(rules, protection), **security}

    def read_rulesets(self, repo: str) -> list[dict[str, Any]]:
        """Full live ruleset payloads (incl. rules), for §5.6 presence + CONTENT drift (read-only).

        The list endpoint returns only summaries, so each ruleset is fetched by id for its rules/
        enforcement. Reading rulesets needs the admin scope (like branch protection), so it runs
        under the same read-only admin token (§11.2) and fails closed as a SettingsReadError — the
        caller then SKIPS settings drift rather than treat a falsely-empty/partial read as "all
        rulesets gone or clean".
        """
        try:
            with github.settings_read_token_scope():
                summaries = github.repository_rulesets(repo)
                payloads: list[dict[str, Any]] = []
                for summary in summaries:
                    ruleset_id = summary.get("id") if isinstance(summary, dict) else None
                    if ruleset_id is None:
                        continue
                    payloads.append(github.repository_ruleset(repo, ruleset_id))
        except github.GitHubAPIError as exc:
            raise github.SettingsReadError(exc.endpoint, exc.returncode, exc.stderr) from exc
        return payloads

    def get_issue(self, repo: str, key: str) -> Issue | None:
        # Fail-closed read (§2.7): the issues-list endpoint returns ``200 []`` when no
        # issue carries the label, so a 404 is the repo itself being absent — both mean
        # "no tracking issue" (default []). An auth/5xx/rate-limit error must RAISE, not
        # masquerade as "no issue": reading it as absent would let run_settings_drift open
        # a duplicate tracking issue (and silently violates its "fails loud" contract).
        # R2-7: paginate the issue list — a label shared by many issues could otherwise hide the
        # active/consent-bearing one on a later page.
        issues = github.gh_json_paginated(f"repos/{repo}/issues?state=all&labels={_seg(key)}", default=[])
        head = _select_issue(issues, repo, key)
        if head is None:
            return None
        # R2-5: more than one OPEN tracking issue for this key is an authorization-ambiguity — consent
        # could be granted on one duplicate while a revoke lives on another. Flag it so reconcile
        # refuses (fail-closed) until the duplicates are closed (§5.7/§5.8).
        open_count = sum(1 for i in issues if isinstance(i, dict) and i.get("state") == "open")
        ambiguous = open_count > 1
        number = head.get("number")
        is_open = head.get("state") == "open"
        if number is None:
            # A 200 with a malformed issue (no number) → can't read the consent timeline;
            # report the issue with no consent so reconcile refuses (fail-safe), never crash.
            return Issue(key=key, open=is_open, ambiguous=ambiguous)

        # Read the FULL (paginated) label-event history so a later revoke cannot be missed
        # (§2.8/§6.4). FAIL CLOSED on a transient error (no allow_error): silently reading
        # the authoritative consent history as [] would drop a real grant/revoke.
        timeline = github.gh_json_paginated(f"repos/{repo}/issues/{number}/timeline", default=[])
        events = _label_events(timeline if isinstance(timeline, list) else [])
        grant = current_consent(events)
        if grant is None:
            return Issue(key=key, open=is_open)

        role, role_ok = self._actor_role(repo, grant.actor_login)
        raw_timeline = timeline if isinstance(timeline, list) else []
        # review #16: map GitHub's actor-type/permission vocabulary to core's NEUTRAL constants at
        # the port boundary, so core/consent.py carries no platform-specific strings (§2.14). A
        # non-"User" type / non-"admin" role maps to a sentinel the gate denies (fail-closed).
        return Issue(
            key=key,
            open=is_open,
            consent_diff_id=grant.diff_id,
            consent_actor_type=ACTOR_HUMAN if grant.actor_type == "User" else "nonhuman",
            consent_role=ROLE_PRIVILEGED if role == "admin" else role,
            consent_role_lookup_ok=role_ok,
            edited_by_nonhuman_since_grant=nonhuman_edit_after_grant(raw_timeline, grant.diff_id),
            ambiguous=ambiguous,
        )

    def probe_health(self, repo: str) -> tuple[bool | None, bool | None]:
        """Probe issue-channel availability and scan-heartbeat presence (§5.4/§5.14).

        Returns ``(issue_channel_available, scan_heartbeat_present)``. A value is
        None when it cannot be determined (e.g. the API call failed) — and a None
        heartbeat reads as broken, never clean (§5.14). Best-effort: a failed probe
        does not raise (doctor is a read-only health report).
        """
        issue_channel: bool | None = None
        heartbeat: bool | None = None
        try:
            repo_data = github.gh_json_optional(f"repos/{repo}", default=None)
            if isinstance(repo_data, dict) and "has_issues" in repo_data:
                issue_channel = bool(repo_data["has_issues"])
            # The heartbeat must be CURRENT, not merely present (§5.14/§8.16). The baseline only
            # uploads it on a CLEAN run (gate-before-upload), but the artifact lingers up to its
            # retention window — so a "clean yesterday, broke today" repo would read clean for days
            # if we checked mere presence. Tie freshness to the current default-branch HEAD: the
            # baseline ran clean on the deployed code iff a non-expired heartbeat exists whose run's
            # head_sha == HEAD. Absence (HEAD's run broke / never ran) reads as broken, not clean.
            branch = repo_data.get("default_branch") if isinstance(repo_data, dict) else None
            head = github.gh_json_optional(f"repos/{repo}/commits/{branch}", default=None) if branch else None
            head_sha = head.get("sha") if isinstance(head, dict) else None
            if head_sha:
                artifacts = github.gh_json_optional(
                    f"repos/{repo}/actions/artifacts?name=aviato-security-heartbeat&per_page=30", default=None
                )
                items = artifacts.get("artifacts", []) if isinstance(artifacts, dict) else []
                heartbeat = any(
                    not item.get("expired") and (item.get("workflow_run") or {}).get("head_sha") == head_sha
                    for item in items
                    if isinstance(item, dict)
                )
        except github.GitHubAPIError:
            pass  # ambiguous read → leave unknown (None)
        return issue_channel, heartbeat

    def _actor_role(self, repo: str, login: str | None) -> tuple[str | None, bool]:
        # §2.7/§6.4 — DELIBERATE: the granter's role is read at apply/get_issue time, not
        # snapshotted at grant time. This is consistent with §2.8 apply-time recompute and fails
        # CLOSED on the dangerous direction (a granter demoted since their grant is now denied).
        # The opposite (a non-admin who grants, then is promoted before reconcile) would be
        # allowed — a bounded TOCTOU widening accepted under the single-operator day-zero scope
        # (§3.4): the same human both grants and applies, so a self-promotion-then-apply is not a
        # privilege-escalation across actors. Revisit if multi-operator consent is added.
        if not login:
            return None, False
        response = github.gh_json(
            f"repos/{repo}/collaborators/{_seg(login)}/permission", default=None, allow_error=True
        )
        if not isinstance(response, dict):
            return None, False  # lookup failed → not authorized (§2.7)
        permission = response.get("permission")
        return (permission, True) if isinstance(permission, str) else (None, False)

    def open_or_update_issue(self, repo: str, key: str, title: str, body: str) -> str:
        # Fail-closed read (§2.7): a transient auth/5xx must RAISE rather than read as "no
        # existing issue", which would POST a DUPLICATE tracking issue every flaky run and
        # fragment the consent/audit trail. A genuine ``200 []`` (no match) still creates one.
        existing = github.gh_json_optional(f"repos/{repo}/issues?state=open&labels={_seg(key)}", default=[])
        # A malformed 200 (issue object without "number") must not crash the scheduled
        # drift-report; fall through to creating a fresh issue rather than KeyError. When
        # several issues share the label, act on ONE deterministically (oldest), with a warn.
        chosen = _select_issue(existing, repo, key)
        number = chosen.get("number") if chosen else None
        if number is not None:
            self._gh_input(["--method", "PATCH", f"repos/{repo}/issues/{number}"], {"body": body})
            return str(number)
        self._gh_input(["--method", "POST", f"repos/{repo}/issues"], {"title": title, "body": body, "labels": [key]})
        return key

    def comment_issue(self, repo: str, key: str, body: str) -> None:
        # Fail-closed read (§2.7): a transient auth/5xx must RAISE rather than silently drop
        # the audit comment (the §5.7 record of a privileged change). A genuine ``200 []``
        # (no issue to comment on) stays a no-op.
        existing = github.gh_json_optional(f"repos/{repo}/issues?state=all&labels={_seg(key)}", default=[])
        chosen = _select_issue(existing, repo, key)
        number = chosen.get("number") if chosen else None
        if number is not None:
            self._gh_input(["--method", "POST", f"repos/{repo}/issues/{number}/comments"], {"body": body})

    def revoke_consent(self, repo: str, key: str, diff_id: str) -> None:
        """Remove the consent-grant label bound to ``diff_id`` from the tracking issue (§5.6/§6.4).

        Called when reported settings drift changes: the prior consent must be VOIDED, not
        merely commented, so a later return to the old diff id cannot re-authorize on a
        stale label (§8.3). Fail-closed: an auth/5xx on the issue read or the label DELETE
        raises (the scheduled run then fails loud, §5.6), while a genuine 404 — the label is
        already absent — is the desired end state and tolerated.
        """
        existing = github.gh_json_optional(f"repos/{repo}/issues?state=all&labels={_seg(key)}", default=[])
        chosen = _select_issue(existing, repo, key)
        number = chosen.get("number") if chosen else None
        if number is None:
            return
        label = f"{CONSENT_LABEL_PREFIX}{diff_id}"
        endpoint = f"repos/{repo}/issues/{number}/labels/{_seg(label)}"
        result = github.run(["gh", "api", "--method", "DELETE", endpoint], check=False)
        if result.returncode != 0 and "http 404" not in result.stderr.lower():
            raise github.GitHubAPIError(endpoint, result.returncode, result.stderr)

    def open_or_update_proposal(self, repo: str, branch: str, title: str, files: dict[str, str], body: str) -> str:
        """Write the regenerated files onto an identity-keyed branch and open/update a PR (§5.5).

        Runs in the checked-out working tree (``workdir``). Requires ``contents:
        write`` (to push the branch) and ``pull-requests: write``. Re-runs converge
        on the same branch, so the existing PR is simply updated by the push.
        """
        base = github.default_branch(repo) or "main"
        owner = repo.split("/", 1)[0]

        for output_path, content in files.items():
            target = self.workdir / output_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        self._git("switch", "-C", branch)
        self._git("add", "--", *files.keys())
        self._git(
            "-c",
            "user.name=aviato-bot",
            "-c",
            "user.email=aviato-bot@users.noreply.github.com",
            # The bot commit must not depend on the operator's signing identity
            # (a global commit.gpgsign would otherwise fail the push, §5.5).
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            title,
        )
        self._git("push", "--force", "origin", branch)

        # Fail-closed read: a 404 cannot occur here (the list is empty when no PR
        # matches), so an auth/5xx error must raise rather than be read as "no existing
        # PR" — which would push a duplicate `pr create`. Consistent with the other reads.
        existing = github.gh_json_optional(f"repos/{repo}/pulls?head={owner}:{branch}&state=open", default=[])
        if not (isinstance(existing, list) and existing):
            self._gh("pr", "create", "--repo", repo, "--head", branch, "--base", base, "--title", title, "--body", body)
        return branch

    def open_worktree_proposal(self, repo: str, branch: str, title: str, body: str) -> str:
        """Commit ALL working-tree changes (incl. deletions) onto an identity-keyed
        branch and open/update a PR (§5.13 offboarding).

        Unlike :meth:`open_or_update_proposal` (which stages a known file set), the caller
        has already mutated the checked-out tree — stripped markers, removed files, deleted
        the declaration — so this stages everything with ``git add -A`` to capture deletions
        too. Runs in ``workdir``; requires ``contents: write`` + ``pull-requests: write``.
        """
        base = github.default_branch(repo) or "main"
        owner = repo.split("/", 1)[0]

        self._git("switch", "-C", branch)
        self._git("add", "-A")
        self._git(
            "-c",
            "user.name=aviato-bot",
            "-c",
            "user.email=aviato-bot@users.noreply.github.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            title,
        )
        self._git("push", "--force", "origin", branch)

        # Fail-closed read: a 404 cannot occur here (the list is empty when no PR
        # matches), so an auth/5xx error must raise rather than be read as "no existing
        # PR" — which would push a duplicate `pr create`. Consistent with the other reads.
        existing = github.gh_json_optional(f"repos/{repo}/pulls?head={owner}:{branch}&state=open", default=[])
        if not (isinstance(existing, list) and existing):
            self._gh("pr", "create", "--repo", repo, "--head", branch, "--base", base, "--title", title, "--body", body)
        return branch

    def _git(self, *args: str) -> None:
        github.run(["git", *args], cwd=self.workdir)

    def _gh(self, *args: str) -> None:
        github.run(["gh", *args], cwd=self.workdir)

    def apply_settings(
        self, repo: str, payload: dict[str, Any], *, expected_live: dict[str, Any] | None = None
    ) -> list[str]:
        # ``payload`` is the flat desired default-branch state; translate it to the
        # branch-protection API shape before the PUT (§2.9). The PUT replaces
        # protection wholesale, so FAIL CLOSED if the live branch carries protections
        # the desired model does not cover (required status checks / push
        # restrictions): silently dropping them would mutate state the operator never
        # saw or consented to (§2.4/§5.7).
        #
        # ``expected_live`` (review #14): the flat live snapshot the consented diff was computed
        # against (§2.8). The fail-closed guards below necessarily re-read live state fresh, which
        # is a SEPARATE snapshot from the one the operator reviewed/consented to. If a MODELED
        # branch-protection field changed between the decision and now, applying the (possibly
        # stale-consented) desired state would write something the operator didn't review against
        # current reality — so re-assert the modeled state is unchanged and abort if it drifted,
        # tying "what is applied" to "what was consented". (Unmodeled protections newly added in
        # the gap are caught by the guards below regardless.)
        branch = github.default_branch(repo)
        if not branch:
            # Empty branch ⇒ ambiguous/transient read. Proceeding would build a
            # `branches//protection` URL that 404s to empty data, silently bypassing the
            # fail-closed unmodeled-protection guards below before the wholesale PUT. Fail
            # closed, mirroring read_settings (§2.7/§2.4).
            raise github.GitHubAPIError(
                f"repos/{repo}", 0, "could not resolve default branch; refusing to apply settings"
            )
        live = github.classic_branch_protection(repo, branch)
        # The wholesale PUT carries only the modeled fields (PR reviews, status checks, force/
        # delete, conversation resolution). Any OTHER classic protection enabled live — push
        # restrictions, linear history, branch lock, code-owner/last-push-approval review gates,
        # etc. — would be silently dropped by the replacement PUT, so fail closed and make the
        # operator reconcile it manually rather than clobber it (§2.4/§2.9).
        unmodeled = [k for k in ("restrictions",) if live.get(k)]
        unmodeled += [k for k in _UNMODELED_CLASSIC_FLAGS if isinstance(live.get(k), dict) and live[k].get("enabled")]
        live_reviews = live.get("required_pull_request_reviews") or {}
        unmodeled += [k for k in _UNMODELED_REVIEW_FIELDS if live_reviews.get(k)]
        # Also inspect branch RULESETS: a rule type the desired model doesn't represent
        # (e.g. commit_message_pattern, required_signatures, required_deployments) would
        # leave a dual-control state the operator never reviewed when the classic PUT
        # lands — fail closed there too (§2.4/§5.7), matching what read_settings reads.
        rules = github.active_branch_rules(repo, branch)
        unmodeled += sorted({str(rule.get("type")) for rule in rules if rule.get("type") not in _MODELED_RULE_TYPES})
        # R2-4: the flat model collapses live required-status-checks to bare context NAMES and the
        # PUT hardcodes strict=true with no app binding. So a live `strict_required_status_checks_
        # policy: false` (which the PUT would flip to true) or an app-BOUND check (carrying an
        # `app_id`, which the PUT would drop the binding of) is unmodeled state the wholesale PUT
        # would silently alter — fail closed rather than clobber (§2.4/§2.9).
        classic_rsc = live.get("required_status_checks") or {}
        if classic_rsc.get("strict") is False:
            unmodeled.append("required_status_checks.strict=false")
        if any(isinstance(c, dict) and c.get("app_id") is not None for c in classic_rsc.get("checks", [])):
            unmodeled.append("required_status_checks.app_bound_checks")
        for rule in rules:
            if rule.get("type") == "required_status_checks":
                params = rule.get("parameters", {})
                if params.get("strict_required_status_checks_policy") is False:
                    unmodeled.append("ruleset.required_status_checks.strict=false")
                if any(
                    isinstance(c, dict) and c.get("integration_id") is not None
                    for c in params.get("required_status_checks", [])
                ):
                    unmodeled.append("ruleset.required_status_checks.app_bound_checks")
        if unmodeled:
            raise UnmodeledProtectionError(
                f"refusing to PUT branch protection on {repo}@{branch}: it carries unmodeled "
                f"protection(s) {unmodeled} that this reconcile does not manage and would drop "
                f"or shadow. Reconcile those manually, then re-run."
            )

        # review #14: re-assert the modeled branch state hasn't drifted since the consented diff
        # was computed (§2.8/§5.7). The decision snapshot (expected_live) and these guard reads are
        # otherwise independent; a modeled-field change in between means the operator consented
        # against stale reality — fail closed and make them re-run, rather than apply a diff that
        # no longer reflects the live state.
        if expected_live is not None:
            fresh_branch = map_branch_settings(rules, live)
            drifted_since = sorted(
                key
                for key in _BRANCH_PROTECTION_KEYS
                if _norm_setting(key, expected_live.get(key)) != _norm_setting(key, fresh_branch.get(key))
            )
            if drifted_since:
                raise UnmodeledProtectionError(
                    f"refusing to apply settings on {repo}@{branch}: its branch protection changed "
                    f"since the reviewed diff was computed ({drifted_since}); re-run reconcile so the "
                    f"applied change reflects current state and your consent (§2.8/§5.7)."
                )

        # Branch protection may be authored on the RULESET surface (the bundled
        # "protect default branch" ruleset) rather than classic protection. This
        # settings reconcile can only write CLASSIC protection, so a classic PUT when a
        # ruleset owns the branch-protection rules would create an unreviewed
        # dual-control divergence — and could silently FAIL to apply a relaxation while
        # reporting success. If the ruleset already enforces the desired branch state
        # there is nothing to write on that surface; otherwise fail closed and direct
        # the operator to the ruleset surface (§2.4/§2.9/§5.7).
        if any(rule.get("type") in _MODELED_RULE_TYPES for rule in rules):
            live_branch = map_branch_settings(rules, live)
            drifted = sorted(
                key
                for key in _BRANCH_PROTECTION_KEYS
                if key in payload and _norm_setting(key, payload[key]) != _norm_setting(key, live_branch.get(key))
            )
            if drifted:
                raise UnmodeledProtectionError(
                    f"refusing to PUT classic branch protection on {repo}@{branch}: its branch "
                    f"protection is enforced by a ruleset, which this settings reconcile cannot "
                    f"write. Reconcile the ruleset with `aviato apply-rulesets {repo}` for {drifted}, "
                    f"then re-run."
                )
        else:
            api_payload = to_branch_protection_payload(payload)
            self._gh_input(["--method", "PUT", f"repos/{repo}/branches/{branch}/protection"], api_payload)

        # Apply the repo-level security toggles (§2.13) when present in the desired set.
        # These are §17 operator-prerequisite features that can be UNAVAILABLE (e.g.
        # secret scanning on a private repo without Advanced Security). An "not
        # available" response is an adoption warning, not an apply failure — surface it
        # and continue; the branch protection (the safety-critical part) already applied.
        # Diagnosis (§5.4) separately probes/surfaces feature availability.
        security_payload = to_security_payload(payload)
        if security_payload:
            try:
                self._gh_input(["--method", "PATCH", f"repos/{repo}"], {"security_and_analysis": security_payload})
            except CommandError as exc:
                if _is_feature_unavailable(exc):
                    print(
                        f"WARNING: repo security features unavailable on {repo} "
                        f"(enable per §17, e.g. Advanced Security): {exc.stderr.strip()}",
                        file=sys.stderr,
                    )
                    # R5-4: the whole security PATCH is skipped (one request for all toggles), so the
                    # desired security keys were NOT applied. Return them so the §5.7 audit reports a
                    # PARTIAL apply rather than overstating a clean one — branch protection still landed.
                    return sorted(security_payload)
                raise
        return []

    def create_repo(self, repo: str, *, private: bool) -> None:
        # §5.2 provision-new: create the repository initialized with a README so the
        # default branch (and its first commit) exists — branch protection cannot be
        # applied to a branch with no commits, so this enables the staged minimal→full
        # ordering (§2.11). Idempotent-ish: a pre-existing repo surfaces as an error.
        args = ["repo", "create", repo, "--add-readme"]
        args.append("--private" if private else "--public")
        github.run(["gh", *args])

    @staticmethod
    def _gh_input(args: list[str], payload: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        try:
            github.run(["gh", "api", *args, "--input", str(path)])
        finally:
            path.unlink(missing_ok=True)
