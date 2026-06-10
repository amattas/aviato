from __future__ import annotations

import argparse
import atexit
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .audit import audit_repos, discover_and_audit, render_json, render_tsv
from .command import CommandError, run
from .core.bootstrap import is_library
from .core.composition import resolve_profile
from .core.declaration import Declaration, declaration_to_yaml, dump_declaration, load_declaration
from .core.diagnosis import ExpectedArtifact, diagnose
from .core.errors import AviatoError, CompatibilityError, DeclarationError
from .core.file_drift_flow import _PROPOSABLE, FileDriftOutcome, run_file_drift
from .core.fleet import RepoScan, scan_fleet
from .core.marker import parse_marker_from_text
from .core.model import ResolvedSet, VariableSpec
from .core.offboarding import offboard as offboard_repo
from .core.onboarding import applicable_templates, materialize_items, plan_onboarding, resolved_artifacts
from .core.provision import provision_repo
from .core.reconcile_flow import run_reconcile
from .core.registry import Registry
from .core.repin import plan_repin
from .core.scaffold import ScaffoldItem, render_managed, scaffold
from .core.settings_drift_flow import run_settings_drift
from .core.variables import resolve_variables, writeback_variables
from .core.version import is_compatible, is_known_version_pin, most_restrictive_recorded, normalize_pin
from .core.versioning import classify_commits, is_highest, next_version
from .github import GitHubAPIError, SettingsReadError, gh_json_paginated_optional, is_archived
from .github_platform import GitHubPlatform, UnmodeledProtectionError
from .paths import MODULE_SOURCE_ROOT, REPO_ROOT
from .plugins.version_formats import bump_files
from .policy import load_policy
from .repos import git_root, is_owner_repo_slug, normalize_slug, remote_url, working_tree_clean
from .rulesets import apply_rulesets, render_all_rulesets
from .validation import validate

# The Library's scheduled drift/report automation workflow identifier (§5.5/§5.6). This is a
# Library artifact name, so it lives OUTSIDE the agnostic core (review #18) and is passed into
# diagnose() as data — core never hardcodes a specific library workflow name.
DRIFT_AUTOMATION_MARKERS = ("reusable-consumer-automation",)
# findings 30/31: the drift caller's repo path, for the API-state probe (enabled +
# last scheduled-run conclusion). A Library artifact name — passed to the binding as
# data, like the markers above.
DRIFT_CALLER_PATH = ".github/workflows/aviato-drift.yml"
LIBRARY_REMOTE_URL = "https://github.com/amattas/aviato.git"


def _non_negative_int(value: str) -> int:
    """argparse type for counts that must be >= 0 (review #11).

    ``--required-approvals`` is injected verbatim into the ruleset payload's
    ``required_approving_review_count``; a negative renders an invalid payload that
    GitHub rejects only at apply time (after work is done), so reject it at parse time.
    """
    parsed = int(value)  # ValueError → argparse reports "invalid _non_negative_int value"
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {parsed}")
    return parsed


def _read_repos_file(path: Path) -> list[str]:
    # R3-13: a missing/unreadable --repos-file must be a clean operator error (exit 2 via main()'s
    # AviatoError handler), not a raw OSError traceback.
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # N8: UnicodeDecodeError is a ValueError, NOT an OSError, so a non-UTF-8 repos file would
        # otherwise escape this net as a raw traceback. Map both to a clean operator error.
        raise AviatoError(f"could not read --repos-file {path}: {exc}") from exc
    repos: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            repos.append(value)
    return repos


def cmd_audit(args: argparse.Namespace) -> int:
    policy = load_policy()  # packaged data root (ships in the wheel; works installed)
    if args.repo:
        repos = []
        for value in args.repo:
            root = git_root(Path(value))
            if root is None:
                print(f"not a git repository: {value}", file=sys.stderr)
                return 2
            repos.append(root)
        rows = audit_repos(repos, root=Path(args.root).resolve(), policy=policy)
    else:
        rows = discover_and_audit(Path(args.root), policy=policy)

    print(render_json(rows) if args.format == "json" else render_tsv(rows))
    return 0


def _profile_status_checks(profile: str | None, overrides: dict[str, object] | None = None) -> list[str]:
    """The resolved profile's required status-check contexts (§10.3 composition; §5.6 gate), or [] if none.

    Lets `apply-rulesets`/`render-rulesets` inject the language verify job (e.g.
    `ci / Python CI`) into the otherwise-static branch ruleset so it matches the
    profile composed for the repo. C12-3: pass the consumer's ``overrides`` so a ruleset
    apply resolves the SAME status checks drift detection uses — never re-adding a check
    the consumer removed via `pipelines.remove`.
    """
    if not profile:
        return []
    from .core.composition import resolve_profile
    from .core.registry import Registry
    from .paths import MODULE_SOURCE_ROOT

    resolved = resolve_profile(Registry(MODULE_SOURCE_ROOT), profile, overrides=overrides or {})
    return list(resolved.settings.get("default_branch", {}).get("required_status_checks", []))


def cmd_apply_rulesets(args: argparse.Namespace) -> int:
    slugs = list(args.repo_pos)
    slugs.extend(args.repo or [])
    if args.repos_file:
        slugs.extend(_read_repos_file(Path(args.repos_file)))

    if not slugs:
        print("at least one repository slug is required", file=sys.stderr)
        return 2

    # R3-5: validate each slug is a clean OWNER/REPO locally (like cmd_provision / the proposals),
    # so a malformed token fails loud here instead of as a confusing 404 after an API round-trip.
    bad = [s for s in slugs if s.count("/") != 1 or not all(part for part in s.split("/"))]
    if bad:
        print(f"invalid repository slug(s) {bad}; expected OWNER/REPO", file=sys.stderr)
        return 2

    # C12-3: if a consumer declaration is given, resolve the profile WITH its overrides so the applied
    # rulesets carry the SAME status checks + approvals drift detection used — never re-adding a check
    # the consumer removed. Otherwise fall back to the base profile (operator-direct provisioning).
    required_approvals = args.required_approvals
    try:
        if getattr(args, "declaration", None):
            declaration = load_declaration(Path(args.declaration))
            extra_checks = _profile_status_checks(declaration.profile, declaration.overrides)
            if required_approvals is None:
                from .core.composition import resolve_profile
                from .core.registry import Registry
                from .paths import MODULE_SOURCE_ROOT

                _db = resolve_profile(
                    Registry(MODULE_SOURCE_ROOT), declaration.profile, overrides=declaration.overrides
                ).settings.get("default_branch", {})
                required_approvals = _db.get("required_reviews")
        else:
            extra_checks = _profile_status_checks(getattr(args, "profile", None))
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.apply:
        # apply-rulesets is operator-DIRECT provisioning (§2.3: human-initiated with
        # own credentials). It is not the §5.7 drift/consent flow — ongoing settings
        # reconciliation should go through `aviato reconcile`, which adds the tracking
        # issue, consent record, and apply-time recompute.
        print(
            "WARNING: applying rulesets directly (operator provisioning). For ongoing "
            "settings drift, use the gated `aviato reconcile` flow (§5.7).",
            file=sys.stderr,
        )

    try:
        for message in apply_rulesets(
            slugs,
            apply=args.apply,
            required_approvals=required_approvals,
            extra_status_checks=extra_checks,
        ):
            print(message)
        return 0
    except (GitHubAPIError, CommandError) as exc:
        # R3-2: the apply WRITE (upsert_ruleset PUT/POST) raises CommandError, not GitHubAPIError;
        # map both to the documented exit 1 instead of letting CommandError fall to main()'s exit 2.
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        # R2-4-5: a malformed ruleset manifest/template (missing rule, unknown patch key, empty name)
        # raises ValueError from render — a library-data error `aviato validate` is meant to catch.
        # Surface it cleanly here rather than leaking a raw traceback past main() (§2.4).
        print(f"ruleset render error (run `aviato validate`): {exc}", file=sys.stderr)
        return 1


def cmd_render_rulesets(args: argparse.Namespace) -> int:
    import json

    try:
        extra_checks = _profile_status_checks(getattr(args, "profile", None))
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        payloads = render_all_rulesets(required_approvals=args.required_approvals, extra_status_checks=extra_checks)
    except ValueError as exc:
        # R2-4-5: malformed ruleset library data → clean error, never a raw traceback (§2.4).
        print(f"ruleset render error (run `aviato validate`): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payloads, indent=2))
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    # `aviato validate` is the LIBRARY's own CI gate (§9/§16): it checks the source tree's
    # workflows/templates/policy infra. From a pip-installed wheel, REPO_ROOT is site-packages —
    # which ships the package data but NOT .github/workflows or templates/ — so refuse with a
    # clear message instead of emitting a pile of spurious "missing required file" errors. (The
    # consumer/operator commands use the packaged data root and work fine when installed.)
    if not (REPO_ROOT / ".github" / "workflows").is_dir():
        print(
            "`aviato validate` runs from a source checkout of the Library (it validates the "
            "policy/workflow infra). It is not meaningful from an installed package.",
            file=sys.stderr,
        )
        return 2
    errors = validate(REPO_ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Aviato validation passed.")
    return 0


def _recorded_versions(root: Path, expected: list[ExpectedArtifact]) -> list[str]:
    """Every version recorded in the consumer's managed markers (§2.6).

    ALL markers are returned (not just the first): mixed marker versions must each be
    checked, or an incompatible one hiding behind a compatible first marker is missed.
    """
    versions: list[str] = []
    for artifact in expected:
        if artifact.seed_once:
            continue
        path = root / artifact.output_path
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # R3-4-1: a non-UTF-8 file at a managed output path carries no valid marker → no
                # version constraint. Skip it (matches diagnosis/scaffold, which treat it as
                # dirty-drift) rather than leak a raw UnicodeDecodeError (a ValueError, outside
                # main()'s except net) that would abort a sync/drift/fleet-scan with a traceback.
                continue
            info = parse_marker_from_text(text)
            if info is not None:
                versions.append(info.version)
    return versions


def _version_pin_error(
    root: Path, declaration: Declaration, expected: list[ExpectedArtifact], override: bool
) -> str | None:
    """Enforce §2.6 version-pin compatibility before a write/proposal; None if OK.

    Skipped in bootstrap (the Library resolves self-references locally, §2.10/§5.10).
    Refuses on a mismatch unless ``override`` is set. Fails CLOSED on an unparseable
    recorded marker (a clean refusal, never an uncaught traceback) and checks EVERY
    recorded marker, not just the first.
    """
    if override or is_library(root):
        return None
    for recorded in _recorded_versions(root, expected) or [declaration.version]:
        try:
            compatible = is_compatible(tool=__version__, pinned=declaration.version, recorded=recorded)
        except CompatibilityError as exc:
            # is_compatible parses all three of tool / pin / recorded marker; any one being
            # unparseable raises here. Surface the exact offending value (the exception names
            # it) rather than always blaming the marker, which may be fine (§2.6 fail-closed).
            return (
                f"version-pin check failed ({exc}): cannot compare tool {__version__}, pin "
                f"{declaration.version!r}, and recorded marker {recorded!r}; refusing to proceed "
                "(pass --override-version-pin to force)"
            )
        if not compatible:
            return (
                f"version-pin mismatch: tool {__version__} is incompatible with pin "
                f"{declaration.version!r} (recorded {recorded!r}); pass --override-version-pin to proceed"
            )
    return None


def _tri(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def _desired_settings(resolved: ResolvedSet) -> dict[str, Any]:
    """Flat reconcilable settings: branch protection + repo security toggles (§5.6/§2.13).

    Rulesets are applied separately (`apply-rulesets`) and are not part of the
    branch-protection/security reconcile diff.

    Filtered to the keys the apply path actually writes (``RECONCILABLE_SETTING_KEYS``): an
    unrecognized key (e.g. a typo in a consumer override) is dropped here so it cannot surface
    as never-converging "phantom drift" that reports + "applies" but changes nothing. The
    Library's own baseline keys are additionally asserted recognized by ``aviato validate``.
    """
    from .github_platform import RECONCILABLE_SETTING_KEYS

    flat = {
        **resolved.settings.get("default_branch", {}),
        **resolved.settings.get("security", {}),
    }
    return {key: value for key, value in flat.items() if key in RECONCILABLE_SETTING_KEYS}


def _drifted_rulesets(
    slug: str,
    platform: GitHubPlatform,
    *,
    required_approvals: int | None = None,
    extra_status_checks: list[str] | None = None,
) -> tuple[str, ...]:
    """Names of desired rulesets MISSING from, or content-DRIFTED on, the live platform (§5.6).

    The GitHub-specific work (render the desired payloads with the resolved verify checks, read
    the live payloads, compare presence + content) lives here in the binding layer, NOT the
    agnostic flow. Reads are admin-scoped and fail closed (SettingsReadError) like other settings
    reads, so the caller's existing fail-closed/fail-loud handling covers them.

    R9-21 (cycle 9, fixed cycle 11): ``extra_status_checks`` is the consumer's **override-resolved**
    required status checks (from ``resolved.settings``), NOT the base profile's. Using the base
    profile here reported phantom drift for a consumer that removed a pipeline via overrides, and the
    suggested `apply-rulesets --profile` remediation would re-add a required check whose workflow no
    longer runs (unmergeable PRs). CX#1: ``required_approvals`` is the resolved ``required_reviews``
    override, flowed in for the same reason (ruleset + classic-protection agree on the count).
    """
    from .rulesets import drifted_ruleset_names, render_all_rulesets

    desired = render_all_rulesets(required_approvals=required_approvals, extra_status_checks=extra_status_checks or [])
    live = platform.read_rulesets(slug)
    return tuple(drifted_ruleset_names(desired, live))


def _expected_artifacts(registry: Registry, declaration: Declaration) -> list[ExpectedArtifact]:
    """The artifacts a consumer should have, honoring its pin, docs, overrides (§5.4).

    Uses the same resolution/rendering/conditional-filtering as sync, so doctor and
    drift expect exactly what sync would write.
    """
    return [
        ExpectedArtifact(a.output, a.body if not a.seed_once else "", a.seed_once)
        for a in resolved_artifacts(
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
            bootstrap=declaration.bootstrap,
            overrides=declaration.overrides,
        )
    ]


def _parse_var_flags(pairs: list[str] | None) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise AviatoError(f"--var expects KEY=VALUE, got {pair!r}")
        key = key.strip()
        # R3-6: an empty key (`--var =v`) or a silently-last-wins duplicate are input footguns;
        # reject both rather than accept silently.
        if not key:
            raise AviatoError(f"--var has an empty key: {pair!r}")
        if key in resolved:
            raise AviatoError(f"--var {key!r} given more than once")
        resolved[key] = value
    return resolved


def _env_vars(specs: Iterable[VariableSpec]) -> dict[str, str]:
    env: dict[str, str] = {}
    for spec in specs:
        key = "AVIATO_VAR_" + spec.name.upper().replace("-", "_")
        if key in os.environ:
            env[spec.name] = os.environ[key]
    return env


def _published_library_ref_exists(pin: str) -> bool:
    """True iff the requested consumer pin resolves to a published Library branch/tag (§6.1)."""
    refs = [f"refs/tags/{pin}", f"refs/heads/{pin}"]
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", LIBRARY_REMOTE_URL, *refs],
            capture_output=True,
            check=False,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _require_published_pin(pin: str, *, allow_unresolved: bool) -> None:
    """Fail closed before writing consumer refs that GitHub cannot resolve (§2.6/§6.1)."""
    if allow_unresolved or _published_library_ref_exists(pin):
        return
    raise DeclarationError(
        f"Library pin {pin!r} does not resolve to a published Aviato branch or tag at {LIBRARY_REMOTE_URL}; "
        "refusing to write consumer workflows that would call a missing reusable workflow ref. "
        "Publish the ref first, or pass --allow-unresolved-pin only for an intentional offline/test scaffold."
    )


def _resolve_onboard_pin(args: argparse.Namespace, existing: Declaration | None) -> str:
    """Resolve the version pin to record (§6.1/§5.12).

    Onboarding must not double as a re-pin. If the repo is already adopted, the
    existing pin is **preserved** unless the operator passes an explicit ``--pin``
    that matches it; an explicit pin that *differs* is refused and the operator is
    directed to ``aviato repin`` — the only sanctioned pin-move path (§5.12), which
    carries the backward-movement warning and identity checks. The returned pin is
    canonical bare SemVer; a legacy leading ``v`` is stripped and never emitted (§6.1).
    """
    explicit = None if args.pin is None else normalize_pin(args.pin)
    if existing is not None:
        # Preserve (and canonicalize) the recorded pin. An unrecognized recorded
        # value is left verbatim — diagnosis classifies it as dirty-drift (§5.4)
        # rather than us guessing or crashing here.
        current = normalize_pin(existing.version) if is_known_version_pin(existing.version) else existing.version
        if explicit is None or explicit == current:
            return current
        raise DeclarationError(
            f"already adopted at version {current!r}; onboarding will not move the pin. "
            f"Use `aviato repin <repo> {explicit}` to change it (§5.12)."
        )
    if explicit is not None:
        _require_published_pin(explicit, allow_unresolved=args.allow_unresolved_pin)
        return explicit
    raise DeclarationError(
        "fresh onboarding requires an explicit --pin (X.Y.Z or N) that already resolves in the "
        "published Aviato Library; bootstrap/local self-reference is only valid for the Library (§2.10/§6.1)."
    )


def _proposal_slug(target: str) -> str:
    """OWNER/REPO for a proposal path, or ``""`` (finding 23).

    An explicit slug argument is validated with the same R2-8 rule apply-rulesets
    enforces (and ``normalize_slug`` applies to remotes) instead of flowing raw —
    ``a/b/c`` or option-shaped tokens previously reached ``gh repo clone`` verbatim.
    """
    if not Path(target).is_dir() and "/" in target:
        return target if is_owner_repo_slug(target) else ""
    return normalize_slug(remote_url(Path(target)))


def _autodetect_vars(target: str) -> dict[str, str]:
    """§5.2 auto-detection tier: only values READ from authoritative sources (finding 28).

    ``owner`` comes from the slug argument (proposal paths) or the repository's own git
    remote — the authoritative identity, not a heuristic guess, so the day-zero "no
    identity-bearing auto-mapping" rule's rationale (wrong guesses get persisted) does
    not apply to it. Absent/foreign remote → empty mapping: the variable stays unset
    and seed-once templates keep their ``{{ owner }}`` placeholder for the operator.
    """
    if not Path(target).is_dir() and is_owner_repo_slug(target):
        return {"owner": target.split("/", 1)[0]}
    slug = normalize_slug(remote_url(Path(target)))
    if slug:
        return {"owner": slug.split("/", 1)[0]}
    return {}


def _resolve_onboard_declaration(
    args: argparse.Namespace, registry: Registry, resolved: ResolvedSet, existing: Declaration | None
) -> tuple[Declaration, dict[str, Any]]:
    """Resolve variables (§5.2 precedence), enforce the migrate guard, resolve the
    version pin (§5.12 re-pin exclusivity), and build the declaration. Raises
    :class:`AviatoError` on a missing required var, a profile change without
    --migrate-profile, or an attempt to move the pin via onboarding; the caller maps
    that to a clean CLI error. Canonicalizes ``args.pin`` in place so the marker
    rendering downstream emits the same bare pin (§6.1)."""
    flags = _parse_var_flags(args.var)
    variables = resolve_variables(
        resolved.variables,
        flags=flags,
        declaration=(existing.variables if existing else {}),
        env=_env_vars(resolved.variables),
        # §5.2 day-zero: the auto-detection tier maps no identity-bearing variable that
        # would be a GUESS — a resolved value is PERSISTED into the declaration and a
        # wrong guess (a directory name is not a PyPI distribution name) is worse than
        # failing closed. The one exception (finding 28, decision recorded in
        # _autodetect_vars): `owner` is read from the repo's own git remote.
        autodetect=_autodetect_vars(args.target),
    )
    plan_onboarding(
        registry,
        profile=args.profile,
        existing_declaration=existing,
        variables=variables,
        allow_migrate=args.migrate_profile,
    )
    pin = _resolve_onboard_pin(args, existing)
    args.pin = pin  # propagate the canonical pin to materialize/scaffold/marker rendering
    persisted = writeback_variables(resolved.variables, variables)
    # §5.2/§6.1: re-onboarding an already-adopted repo must PRESERVE its opt-in docs choice (like
    # overrides). --docs only ever ENABLES; a re-run without it must not silently flip docs:true
    # back to false. (Disabling docs is a deliberate reduction the operator makes in the file.)
    docs = args.docs or (existing.docs if existing else False)
    declaration = Declaration(
        profile=args.profile,
        version=pin,
        docs=docs,
        variables=persisted,
        overrides=(existing.overrides if existing else {}),
    )
    return declaration, variables


def _onboard_write(args: argparse.Namespace, registry: Registry, resolved: ResolvedSet) -> int:
    """Adopt a local repository (§5.2): resolve variables, write the declaration, scaffold."""
    target = Path(args.target)
    if not target.is_dir():
        print(f"--write requires a local repository path; {args.target!r} is not a directory", file=sys.stderr)
        return 2

    # §5.2 adopt precondition: the working tree must be clean (so the scaffold lands as
    # a reviewable change), unless the operator explicitly overrides.
    if not args.allow_dirty and not working_tree_clean(target):
        print(
            "working tree is not clean; commit/stash first or pass --allow-dirty (§5.2).",
            file=sys.stderr,
        )
        return 2

    declaration_path = target / ".github" / "aviato.yaml"
    existing = load_declaration(declaration_path) if declaration_path.is_file() else None

    try:
        declaration, variables = _resolve_onboard_declaration(args, registry, resolved, existing)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    declaration_path.parent.mkdir(parents=True, exist_ok=True)
    dump_declaration(declaration, declaration_path)
    print(f"wrote {declaration_path.relative_to(target)}")

    # Scaffold with the RESOLVED declaration.docs (the preserved/effective value), so the docs
    # artifacts always match what the declaration records (§5.2/§6.1/§13.3) — never args.docs.
    items = materialize_items(
        registry,
        args.profile,
        variables,
        pin=args.pin,
        docs=declaration.docs,
        bootstrap=declaration.bootstrap,
        overrides=declaration.overrides,
    )
    result = scaffold(target, items, profile=args.profile, version=args.pin)
    for output in result.written:
        print(f"wrote {output}")
    for output in result.seeded:
        print(f"seeded {output}")
    for output in result.skipped_unmanaged + result.skipped_modified:
        # review #30: a marker-less file at a managed output path (e.g. a formerly-managed file left
        # by `offboard --keep-files`, or a hand-edited one) is never silently clobbered; surface it
        # and tell the operator how to (re-)adopt it as managed, so the orphaned state isn't hidden.
        print(f"SKIPPED (operator-owned; run `aviato sync --force` to (re-)adopt as managed) {output}")
    for output in result.skipped_foreign:
        print(
            "SKIPPED (marker from a different profile or unknown version — run `aviato sync --force` "
            f"to overwrite) {output}"
        )
    print(
        "next: review the changes, then apply protections with "
        f"`aviato apply-rulesets OWNER/REPO --apply --profile {args.profile}` "
        "(--profile injects the profile's language verify check into the ruleset)."
    )
    return 0


def _onboard_proposal(args: argparse.Namespace, registry: Registry, resolved: ResolvedSet) -> int:
    """Adopt an EXISTING repository via a proposal (§5.2): scaffold the declaration +
    managed artifacts onto a branch and open a PR, enumerating untouched seed-once /
    operator-owned files. Non-destructive: works in a fresh temp clone, never the
    operator's checkout."""
    slug = _proposal_slug(args.target)
    if not slug:
        print(
            "could not determine a valid OWNER/REPO (pass a clean owner/repo slug, or a local "
            "repo with a github remote)",
            file=sys.stderr,
        )
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="aviato-onboard-"))
    # The CLI runs one command per process; clean the full clone at exit so repeated runs
    # don't leak hundreds of MB into the temp dir regardless of which return path is taken.
    atexit.register(shutil.rmtree, workdir, True)
    clone = workdir / "repo"
    try:
        run(["gh", "repo", "clone", slug, str(clone)])
    except CommandError as exc:
        print(f"could not clone {slug}: {exc}", file=sys.stderr)
        return 1

    declaration_path = clone / ".github" / "aviato.yaml"
    existing = load_declaration(declaration_path) if declaration_path.is_file() else None
    try:
        declaration, variables = _resolve_onboard_declaration(args, registry, resolved, existing)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Build the proposal file set: the declaration + managed (marker-stamped) bodies +
    # seed-once bodies for files that DON'T already exist. Existing seed-once / operator
    # files are left untouched and enumerated (§5.2).
    files: dict[str, str] = {".github/aviato.yaml": declaration_to_yaml(declaration)}
    untouched: list[str] = []
    # Use the RESOLVED declaration.docs (preserved from the clone's existing declaration), so the
    # proposed docs artifacts match the declaration written above — never the raw args.docs (§13.3).
    for artifact in resolved_artifacts(
        registry,
        args.profile,
        variables,
        pin=args.pin,
        docs=declaration.docs,
        bootstrap=declaration.bootstrap,
        overrides=declaration.overrides,
    ):
        present = (clone / artifact.output).exists()
        if artifact.seed_once:
            if present:
                untouched.append(artifact.output)
                continue
            files[artifact.output] = artifact.body
        else:
            item = ScaffoldItem(output=artifact.output, body=artifact.body, comment=artifact.comment)
            files[artifact.output] = render_managed(item, profile=args.profile, version=args.pin)

    body_lines = [
        "Aviato onboarding proposal (§5.2 adopt-existing).",
        "",
        f"Profile: `{args.profile}` · pin `{args.pin}` · docs={declaration.docs}",
        "",
        "Adds the declaration and managed artifacts on this branch for review.",
    ]
    if untouched:
        body_lines += ["", "Left untouched (seed-once already present / operator-owned):"]
        body_lines += [f"- `{p}`" for p in untouched]
    branch = f"aviato/onboard-{args.profile}"
    title = f"Adopt Aviato conventions ({args.profile})"
    try:
        GitHubPlatform(workdir=clone).open_or_update_proposal(slug, branch, title, files, "\n".join(body_lines))
    except (GitHubAPIError, CommandError) as exc:
        print(f"could not open onboarding proposal: {exc}", file=sys.stderr)
        return 1

    print(f"opened onboarding proposal for {slug} on branch {branch} ({len(files)} files).")
    for p in untouched:
        print(f"untouched (left for the operator): {p}")
    print(
        "next: review + merge the PR, then apply protections "
        f"(`aviato complete-protection` or `aviato apply-rulesets OWNER/REPO --apply --profile {args.profile}`)."
    )
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    if args.write and args.open_pr:
        print("--write and --open-pr are mutually exclusive (local adoption vs. a PR proposal)", file=sys.stderr)
        return 2
    # §5.2/§6.1: re-onboarding an already-adopted repo PRESERVES its opt-in docs choice — --docs
    # only ENABLES, a re-run without it must not silently drop docs:true (and then write a docs:true
    # declaration with no docs artifacts). Apply it to the resolved set + plan here for a LOCAL
    # target; the --open-pr path reads the existing from its clone and uses declaration.docs.
    if not args.docs:
        decl_path = Path(args.target) / ".github" / "aviato.yaml"
        if decl_path.is_file():
            with contextlib.suppress(AviatoError):
                args.docs = load_declaration(decl_path).docs
    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        resolved = resolve_profile(registry, args.profile, docs=args.docs)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.open_pr:
        return _onboard_proposal(args, registry, resolved)
    if args.write:
        return _onboard_write(args, registry, resolved)

    # R3-4/R3-15: validate --var and --pin and run the same existing-declaration guard the
    # write/proposal paths use BEFORE emitting any plan, so the dry-run never prints a partial plan
    # for an invalid --var/--pin, nor a plan for an action --write would refuse (a profile change
    # without --migrate-profile).
    known_vars = _parse_var_flags(args.var)
    canonical_pin = normalize_pin(args.pin) if args.pin is not None else None
    decl_path = Path(args.target) / ".github" / "aviato.yaml"
    if decl_path.is_file():
        existing = load_declaration(decl_path)
        if existing.profile != args.profile and not getattr(args, "migrate_profile", False):
            raise AviatoError(
                f"repository already declares profile {existing.profile!r}; pass --migrate-profile "
                f"to change it to {args.profile!r} (the plan mirrors what --write would refuse)"
            )

    print(f"Onboarding plan for {args.target}")
    print(f"profile: {resolved.profile}")
    if canonical_pin is not None:
        # review #29: preview the canonical pin the write would record (§6.1).
        print(f"version pin: {canonical_pin}")

    print("pipelines:")
    for pipeline in resolved.pipelines:
        print(f"- {pipeline}")

    print("templates:")
    # Apply the §12.2/§6.1 conditional filter so the preview lists the *exact* artifacts
    # --write would materialize — no over-reporting. The known variables are the profile's
    # defaults plus any supplied --var (the same set --write resolves from), so a template
    # gated on an unsupplied/unmatched variant is excluded, not shown alongside its sibling.
    known: dict[str, Any] = {spec.name: spec.default for spec in resolved.variables if spec.default is not None}
    known.update(known_vars)
    known["docs"] = "true" if args.docs else "false"
    for template in applicable_templates(resolved, known):
        kind = "seed-once" if template.seed_once else "managed"
        print(f"- {template.output_path} ({kind})")

    if resolved.variables:
        print("variables:")
        for variable in resolved.variables:
            secret = ", secret" if variable.secret else ""
            optional = "" if variable.required else ", optional"
            print(f"- {variable.name} ({variable.type}{optional}{secret})")

    print("settings:")
    # List the rulesets `apply-rulesets` will actually apply — the rendered MANIFEST, the single
    # source of truth — not resolved.settings["rulesets"] (a consumer override deep-merges that
    # list, §4.2, and it would otherwise mislead the plan without affecting what is applied).
    from .rulesets import render_all_rulesets

    for payload in render_all_rulesets(extra_status_checks=_profile_status_checks(args.profile)):
        print(f"- ruleset: {payload['name']}")

    print("next command:")
    print(f"aviato apply-rulesets {args.target} --apply --profile {args.profile}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        resolved = resolve_profile(
            registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs
        )
        expected = _expected_artifacts(registry, declaration)
        secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
        prerequisite_paths = registry.profile_doc(declaration.profile).get("prerequisites", {})
        # diagnose() rejects a bootstrap declaration in a non-Library repo (§5.4/§5.10); keep it
        # inside the handler so that rejection surfaces as a clean operator error, not a traceback.
        report = diagnose(
            root,
            expected,
            declaration_variables=declaration.variables,
            secret_var_names=secret_names,
            prerequisite_paths=prerequisite_paths,
            drift_automation_markers=DRIFT_AUTOMATION_MARKERS,
            profile=declaration.profile,
            is_library=is_library(root),
            bootstrap_declared=declaration.bootstrap,
        )
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Platform-dependent probes (§5.4/§5.14): issue-channel availability and the
    # per-run scan heartbeat. Best-effort — populated only if a repo slug resolves.
    slug = normalize_slug(remote_url(root))
    if slug and not args.no_remote_probe:
        # R7-3-APPSTORE-ENV: derive the list of environments to probe from the resolved profile's
        # pipelines (plug-in DATA, §9b — the binding/core stay agnostic to which capability requires
        # which env name). Today only app-store-connect declares one; future deploy pipelines that
        # require a protected environment can add the field without code changes here.
        environments = tuple(sorted({p.environment for p in resolved.pipeline_modules if p.environment}))
        (
            report.issue_channel_available,
            report.scan_heartbeat_present,
            report.prerequisites_remote,
        ) = GitHubPlatform().probe_health(
            slug,
            environments=environments,
            probe_pages=declaration.docs,
            # findings 30/31/32: API-state probes — drift caller enabled + last-run
            # conclusion, and code-scanning enablement (§2.13/§17 "probeable").
            drift_workflow_path=DRIFT_CALLER_PATH,
        )

    print(f"doctor: {declaration.profile} @ {declaration.version} ({root})")
    for output_path, status in sorted(report.statuses.items()):
        print(f"- {output_path}: {status}")
    if report.seed_divergence:
        print("seed-once integrity divergence (report-only):")
        for path in sorted(report.seed_divergence):
            print(f"- {path}")
    if report.secret_in_declaration:
        print("WARNING: secret-typed variable present in declaration (§6.6/§8.15)")
    print(f"drift automation present: {'yes' if report.drift_automation_present else 'no'}")
    print("prerequisites:")
    for name, ok in sorted(report.prerequisites.items()):
        print(f"- {name}: {'ok' if ok else 'missing'}")
    print(f"issue channel available: {_tri(report.issue_channel_available)}")
    print(f"scan heartbeat present: {_tri(report.scan_heartbeat_present)} (absence reads as broken, §5.14)")
    if report.prerequisites_remote:
        # R6-2-§17-PROBE: §17 items the binding probed remotely (security toggles + Pages source).
        # Absence/unknown reads as broken (§5.14) — operator should enable per §17, then re-run.
        print("remote prerequisites (§17):")
        for name, value in sorted(report.prerequisites_remote.items()):
            print(f"- {name}: {_tri(value)}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        items = materialize_items(
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
            bootstrap=declaration.bootstrap,
            overrides=declaration.overrides,
        )
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    expected = [ExpectedArtifact(i.output, i.body, i.seed_once) for i in items]
    pin_error = _version_pin_error(root, declaration, expected, args.override_version_pin)
    if pin_error:
        print(pin_error, file=sys.stderr)
        return 2

    result = scaffold(
        root,
        items,
        profile=declaration.profile,
        version=declaration.version,
        force=args.force,
    )
    for output in result.written:
        print(f"wrote {output}")
    for output in result.seeded:
        print(f"seeded {output}")
    for output in result.unchanged:
        print(f"unchanged {output}")
    for output in result.skipped_unmanaged:
        print(f"SKIPPED (unmanaged/malformed) {output}")
    for output in result.skipped_modified:
        print(f"SKIPPED (hand-edited — use --force to overwrite) {output}")
    for output in result.skipped_foreign:
        print(f"SKIPPED (marker from a different profile or unknown version — use --force to overwrite) {output}")
    return 0


def _scan_has_file_drift(scan: RepoScan) -> bool:
    # A repo is fixable by --fix iff it has a proposable managed-file status. Reuse
    # file_drift_flow._PROPOSABLE directly (not a copy) so the scan gate can never drift
    # from what run_file_drift actually proposes; "dirty-drift" stays excluded (§5.4/§5.5).
    return any(status in _PROPOSABLE for status in scan.statuses.values())


def _archived_probe(root: Path) -> bool | None:
    """Best-effort archived check for §5.11 (the platform-touching part, kept out of core).

    Resolves the repo's remote slug and reads its archived flag. Any failure (no remote,
    offline, ambiguous read) yields None → treated as not-archived, so a repo is never
    silently skipped on an unreadable probe.
    """
    try:
        slug = normalize_slug(remote_url(root))
        if not slug:
            return None
        return is_archived(slug)
    except (GitHubAPIError, CommandError):
        return None


def cmd_scan(args: argparse.Namespace) -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    scans = scan_fleet(
        [Path(p) for p in args.paths],
        registry,
        include_archived=args.include_archived,
        archived_probe=_archived_probe,
        # finding 33: full §5.4 parity with doctor — the fleet sweep probes the drift
        # automation and §17 prerequisites too.
        drift_automation_markers=DRIFT_AUTOMATION_MARKERS,
    )
    rc = 0
    for scan in scans:
        if scan.skipped_archived:
            print(f"{scan.path}\tSKIPPED: archived (pass --include-archived to scan it)")
            continue
        if scan.error:
            # A per-repo error must make the exit code non-zero (rc=1): operators gate CI on
            # `aviato scan` over a fleet, and an all-errors run reporting success would mask a
            # broken fleet. Error rows go to stderr so the stdout TSV stays machine-parseable.
            print(f"{scan.path}\tERROR: {scan.error}", file=sys.stderr)
            rc = 1
            continue
        summary = ", ".join(f"{output}={status}" for output, status in sorted(scan.statuses.items())) or "—"
        flags = " [secret-in-declaration]" if scan.secret_in_declaration else ""
        print(f"{scan.path}\t{scan.profile}\t{summary}{flags}")
        # §6.3 seed-once integrity divergence (tamper/deletion) must surface in the fleet sweep,
        # not only in `doctor` — otherwise the scale-out command silently drops the one signal
        # seed-once tracking exists to provide.
        if scan.seed_divergence:
            print(f"  seed divergence: {', '.join(sorted(scan.seed_divergence))}", file=sys.stderr)
        # finding 33: the §5.4 probes the sweep previously dropped.
        if scan.drift_automation_present is False:
            print("  drift automation: MISSING", file=sys.stderr)
        missing_prereqs = sorted(name for name, ok in scan.prerequisites.items() if not ok)
        if missing_prereqs:
            print(f"  missing prerequisites: {', '.join(missing_prereqs)}", file=sys.stderr)
        if args.audit:
            _print_repo_audit(Path(scan.path))
        if args.fix and _scan_has_file_drift(scan):
            try:
                outcome = _propose_file_drift(registry, Path(scan.path), override_version_pin=args.override_version_pin)
                print(f"  fix: proposed={outcome.proposed} dirty={outcome.dirty}")
            except (AviatoError, GitHubAPIError, CommandError) as exc:
                # R3-1: open_or_update_proposal's git/gh writes raise CommandError; without it in
                # the tuple a push failure escapes to main() and aborts the whole fleet sweep.
                print(f"  fix ERROR: {exc}", file=sys.stderr)
                rc = 1
    return rc


def _print_repo_audit(root: Path) -> None:
    """§5.11 read-only audit aggregation (finding 36): the per-Consumer audit trail
    already lives on each repo's tracking issues — surface the open settings-drift
    issue inline so fleet-level visibility doesn't require visiting every repo.
    Ephemeral operator-side OUTPUT only — no inventory is stored (§2.2); a per-repo
    read failure degrades to a note, never aborts the sweep."""
    slug = normalize_slug(remote_url(root))
    if not slug:
        print("  audit: no github remote", file=sys.stderr)
        return
    try:
        issues = gh_json_paginated_optional(
            f"repos/{slug}/issues?state=open&labels={quote(SETTINGS_DRIFT_ISSUE_KEY, safe='')}", default=[]
        )
    except GitHubAPIError as exc:
        print(f"  audit: unreadable ({exc})", file=sys.stderr)
        return
    rows = [issue for issue in issues if isinstance(issue, dict)] if isinstance(issues, list) else []
    if not rows:
        print("  audit: no open settings-drift issue")
        return
    for issue in rows:
        print(f"  audit: #{issue.get('number')} {str(issue.get('title'))!r} updated {issue.get('updated_at')}")


def _propose_file_drift(registry: Registry, root: Path, *, override_version_pin: bool = False) -> FileDriftOutcome:
    """Open a managed-file drift proposal for one repo (§5.5), shared by scan --fix.

    Resolves the repo's declaration, re-diagnoses, and routes the same
    marker-stamped bodies scaffold() would write through ``run_file_drift`` so a
    merged PR classifies clean (§6.2/§5.4). Enforces the §2.6 version-pin gate first
    — exactly like ``drift-report``/``sync`` — so an incompatible local tool cannot
    regenerate a consumer's files (unless the operator passes --override-version-pin).
    """
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        raise AviatoError(f"no declaration at {declaration_path}")

    declaration = load_declaration(declaration_path)
    expected = _expected_artifacts(registry, declaration)
    # §2.6 pin gate before any remote/proposal work (matches drift-report/sync): an
    # incompatible local tool must not regenerate a consumer's files via scan --fix.
    pin_error = _version_pin_error(root, declaration, expected, override_version_pin)
    if pin_error:
        raise AviatoError(pin_error)

    slug = normalize_slug(remote_url(root))
    if not slug:
        raise AviatoError("could not determine OWNER/REPO from the repository remote")
    resolved = resolve_profile(registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs)
    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    report = diagnose(
        root,
        expected,
        declaration_variables=declaration.variables,
        secret_var_names=secret_names,
        profile=declaration.profile,
        is_library=is_library(root),
        bootstrap_declared=declaration.bootstrap,
    )

    managed_bodies: dict[str, str] = {}
    for artifact in resolved_artifacts(
        registry,
        declaration.profile,
        declaration.variables,
        pin=declaration.version,
        docs=declaration.docs,
        bootstrap=declaration.bootstrap,
        overrides=declaration.overrides,
    ):
        if artifact.seed_once:
            continue
        item = ScaffoldItem(output=artifact.output, body=artifact.body, comment=artifact.comment)
        managed_bodies[artifact.output] = render_managed(item, profile=declaration.profile, version=declaration.version)

    # review #5: drift is DIAGNOSED against the operator's local tree (above), but the proposal
    # must be pushed from a FRESH CLONE — never the operator's live checkout. open_or_update_proposal
    # does `git switch -C` + `git push --force` in its workdir; doing that in `root` would rip the
    # operator's checkout onto the proposal branch and clobber uncommitted work (and race a second
    # scan). The regenerated bodies come from the library, so they're identical regardless of which
    # tree they're written into. Mirrors the onboard/offboard --open-pr isolation.
    workdir = Path(tempfile.mkdtemp(prefix="aviato-scanfix-"))
    atexit.register(shutil.rmtree, workdir, True)
    clone = workdir / "repo"
    try:
        run(["gh", "repo", "clone", slug, str(clone)])
    except CommandError as exc:
        raise AviatoError(f"could not clone {slug} to propose a fix: {exc}") from exc

    return run_file_drift(
        GitHubPlatform(workdir=clone),
        repo=slug,
        profile=declaration.profile,
        statuses=report.statuses,
        expected_bodies=managed_bodies,
        is_bootstrap=is_library(root),
    )


def _gate_repin_target(root: Path | None, target_version: str, args: argparse.Namespace) -> str | None:
    """The two repin write-gates (finding 9); an error message, or None when clear.

    repin is the ONLY sanctioned pin move, yet it skipped both gates onboard/provision
    fail closed on: (a) the target must resolve to a PUBLISHED Library ref — a typo'd
    target writes ``uses: …@X.Y.Z`` refs GitHub cannot resolve; (b) §2.6 — the running
    tool must be compatible with the TARGET pin ("must refuse to act on a mismatch,
    unless explicitly overridden").
    """
    try:
        _require_published_pin(target_version, allow_unresolved=args.allow_unresolved_pin)
    except AviatoError as exc:
        return str(exc)
    if args.override_version_pin or (root is not None and is_library(root)):
        return None
    # Major-line check only: a same-major forward re-pin is the normal §5.12 move (the
    # CONSUMER runs the target's workflows, not this tool's); a CROSS-major target means
    # this tool's templates are not that major's templates — refuse unless overridden.
    try:
        tool_major = int(__version__.split(".", 1)[0])
        target_major = int(str(target_version).split(".", 1)[0])
    except ValueError:
        return f"version-pin check failed: cannot parse tool {__version__!r} / target {target_version!r} (§2.6)"
    if tool_major != target_major:
        return (
            f"version-pin mismatch: tool {__version__} (major {tool_major}) cannot stamp target "
            f"pin {target_version!r} (major {target_major}); use a matching Aviato release or pass "
            "--override-version-pin (§2.6)"
        )
    return None


def cmd_repin(args: argparse.Namespace) -> int:
    """Move a consumer to a different Library version (§5.12) — the only sanctioned pin move."""
    if args.write and args.open_pr:
        print("--write and --open-pr are mutually exclusive (local re-pin vs. a PR proposal)", file=sys.stderr)
        return 2
    if args.open_pr:
        return _repin_proposal(args)

    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        plan = plan_repin(registry, declaration, args.version)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"re-pin {declaration.version} -> {plan.target_version}")
    if plan.downgrade_warning:
        print(f"WARNING: {plan.downgrade_warning}")
    for name in plan.newly_required:
        print(f"  newly-required variable (set before re-pinning): {name}")
    for key in plan.orphaned_overrides:
        print(f"  orphaned settings override (no longer in the profile): {key}")
    for name in plan.conflicting_overrides:
        print(f"  conflicting pipelines.add override (now bundled at the target): {name}")
    if not plan.ok:
        if plan.conflicting_overrides:
            print(
                "re-pin blocked: remove the conflicting pipelines.add override(s) — the target "
                "version already bundles them (§5.12/§4.2).",
                file=sys.stderr,
            )
        if plan.newly_required:
            print("re-pin blocked: supply the newly-required variables first.", file=sys.stderr)
        return 1

    if not args.write:
        print("dry run; re-run with --write to record the new pin and re-scaffold.")
        return 0

    if (gate_error := _gate_repin_target(root, plan.target_version, args)) is not None:
        print(gate_error, file=sys.stderr)
        return 2

    updated = Declaration(
        profile=declaration.profile,
        version=plan.target_version,
        docs=declaration.docs,
        bootstrap=declaration.bootstrap,
        variables=declaration.variables,
        overrides=declaration.overrides,
    )
    # R3-4-3: render the new-pin artifacts BEFORE persisting the pin, so a render-time failure aborts
    # the re-pin without leaving the declaration moved to the new pin but the managed files still at
    # the old one (a non-transactional state that a re-run would report as `X -> X` and re-fail).
    items = materialize_items(
        registry,
        updated.profile,
        updated.variables,
        pin=updated.version,
        docs=updated.docs,
        bootstrap=updated.bootstrap,
        overrides=updated.overrides,
    )
    dump_declaration(updated, declaration_path)
    print(f"wrote pin {plan.target_version} to {declaration_path.relative_to(root)}")
    result = scaffold(root, items, profile=updated.profile, version=updated.version)
    for output in result.written:
        print(f"rewrote {output}")
    # §5.12: surface files the no-clobber guard left at the OLD pin so the operator
    # knows the re-pin did not fully apply (a silent skip would misrepresent success).
    for output in result.skipped_modified:
        print(f"skipped (hand-edited; still at old pin — reconcile manually): {output}")
    for output in result.skipped_unmanaged:
        print(f"skipped (unmanaged file at this path — not re-pinned): {output}")
    for output in result.skipped_foreign:
        print(
            "skipped (marker from a different profile or unknown version; still at old pin — run "
            f"`aviato sync --force`): {output}"
        )
    print("next: review the re-pinned artifacts, commit on a branch, and open a PR (§5.2/§5.12).")
    return 0


def _repin_proposal(args: argparse.Namespace) -> int:
    """Re-pin via a reviewable proposal (§5.12, finding 35): in a fresh temp clone,
    re-render the managed artifacts at the target pin and open a PR carrying the
    backward-movement warning. Non-destructive to the operator's checkout — the
    propose path §5.12 describes, mirroring onboard/offboard --open-pr."""
    slug = _proposal_slug(args.path)
    if not slug:
        print(
            "could not determine a valid OWNER/REPO (pass a clean owner/repo slug, or a local "
            "repo with a github remote)",
            file=sys.stderr,
        )
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="aviato-repin-"))
    atexit.register(shutil.rmtree, workdir, True)  # clean the clone at exit (one command per process)
    clone = workdir / "repo"
    try:
        run(["gh", "repo", "clone", slug, str(clone)])
    except CommandError as exc:
        print(f"could not clone {slug}: {exc}", file=sys.stderr)
        return 1

    declaration_path = clone / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}; onboard first", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        plan = plan_repin(registry, declaration, args.version)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not plan.ok:
        for name in plan.newly_required:
            print(f"newly-required variable (set before re-pinning): {name}", file=sys.stderr)
        for name in plan.conflicting_overrides:
            print(f"conflicting pipelines.add override (now bundled at the target): {name}", file=sys.stderr)
        print("re-pin blocked; resolve the above first (§5.12).", file=sys.stderr)
        return 1
    if (gate_error := _gate_repin_target(clone, plan.target_version, args)) is not None:
        print(gate_error, file=sys.stderr)
        return 2

    updated = Declaration(
        profile=declaration.profile,
        version=plan.target_version,
        docs=declaration.docs,
        bootstrap=declaration.bootstrap,
        variables=declaration.variables,
        overrides=declaration.overrides,
    )
    try:
        items = materialize_items(
            registry,
            updated.profile,
            updated.variables,
            pin=updated.version,
            docs=updated.docs,
            bootstrap=updated.bootstrap,
            overrides=updated.overrides,
        )
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    dump_declaration(updated, declaration_path)
    result = scaffold(clone, items, profile=updated.profile, version=updated.version)

    body_lines = [
        f"Aviato re-pin proposal (§5.12): {declaration.version} -> {plan.target_version}.",
        "",
        f"- rewrote {len(result.written)} managed file(s) at the target pin",
    ]
    if plan.downgrade_warning:
        body_lines[1:1] = ["", f"WARNING: {plan.downgrade_warning}"]
    for output in result.skipped_modified:
        body_lines.append(f"- skipped (hand-edited; still at old pin): {output}")
    branch = f"aviato/repin-{plan.target_version}"
    title = f"chore: re-pin Aviato to {plan.target_version} (§5.12)"
    try:
        GitHubPlatform(workdir=clone).open_worktree_proposal(slug, branch, title, "\n".join(body_lines))
    except (GitHubAPIError, CommandError) as exc:
        print(f"could not open re-pin proposal: {exc}", file=sys.stderr)
        return 1

    print(f"opened re-pin proposal for {slug} on branch {branch}.")
    if plan.downgrade_warning:
        print(f"WARNING: {plan.downgrade_warning}")
    return 0


def cmd_offboard(args: argparse.Namespace) -> int:
    """Remove a consumer from Aviato management (§5.13)."""
    if args.write and args.open_pr:
        print("--write and --open-pr are mutually exclusive (local removal vs. a PR proposal)", file=sys.stderr)
        return 2
    if args.open_pr:
        return _offboard_proposal(args)

    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    managed_outputs = [a.output_path for a in expected if not a.seed_once]
    if not args.write:
        from .core.offboarding import BASELINE_REMOVAL_WARNING

        if args.delete_files:
            print(
                f"dry run; would delete {len(managed_outputs)} managed file(s), then remove the declaration + sidecar."
            )
        else:
            print(
                f"dry run; would strip markers from {len(managed_outputs)} managed file(s) "
                "(automation workflows under .github/workflows are deleted, not just stripped, §5.13), "
                "then remove the declaration + sidecar."
            )
        print(f"WARNING: {BASELINE_REMOVAL_WARNING}")
        print("re-run with --write to perform the removal.")
        return 0

    result = offboard_repo(root, managed_outputs, keep_files=not args.delete_files)
    for output in result.stripped:
        print(f"stripped marker: {output}")
    for output in result.removed:
        print(f"removed: {output}")
    if result.declaration_removed:
        print("removed .github/aviato.yaml")
    if result.sidecar_removed:
        print("removed .github/aviato.seed.json")
    print(f"WARNING: {result.warning}")
    return 0


def _offboard_proposal(args: argparse.Namespace) -> int:
    """Offboard via a reviewable proposal (§5.13): in a fresh temp clone, strip/remove the
    managed files, remove the consumer automation, delete the declaration, then open a PR
    carrying the §2.13 baseline-removal warning. Non-destructive to the operator's checkout."""
    slug = _proposal_slug(args.path)
    if not slug:
        print(
            "could not determine a valid OWNER/REPO (pass a clean owner/repo slug, or a local "
            "repo with a github remote)",
            file=sys.stderr,
        )
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="aviato-offboard-"))
    atexit.register(shutil.rmtree, workdir, True)  # clean the clone at exit (one command per process)
    clone = workdir / "repo"
    try:
        run(["gh", "repo", "clone", slug, str(clone)])
    except CommandError as exc:
        print(f"could not clone {slug}: {exc}", file=sys.stderr)
        return 1

    declaration_path = clone / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}; nothing to offboard", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    managed_outputs = [a.output_path for a in expected if not a.seed_once]
    result = offboard_repo(clone, managed_outputs, keep_files=not args.delete_files)

    body_lines = [
        "Aviato offboarding proposal (§5.13).",
        "",
        f"WARNING: {result.warning}",
        "",
        f"- stripped markers from {len(result.stripped)} file(s)",
        f"- removed {len(result.removed)} managed file(s)",
        "- removed the declaration and seed-once sidecar",
        "- removed the scheduled consumer drift/report automation",
    ]
    branch = "aviato/offboard"
    title = "Offboard from Aviato management (§5.13)"
    try:
        GitHubPlatform(workdir=clone).open_worktree_proposal(slug, branch, title, "\n".join(body_lines))
    except (GitHubAPIError, CommandError) as exc:
        print(f"could not open offboarding proposal: {exc}", file=sys.stderr)
        return 1

    print(f"opened offboarding proposal for {slug} on branch {branch}.")
    print(f"WARNING: {result.warning}")
    return 0


def cmd_complete_protection(args: argparse.Namespace) -> int:
    """Idempotently (re-)apply full branch protection after onboarding (§5.2 recovery).

    Safe to re-run any number of times: it applies the full desired protected-settings
    state for the repo's resolved profile. This is operator-DIRECT provisioning (§2.3),
    not the gated §5.7 drift/consent flow.
    """
    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    slug = normalize_slug(remote_url(root))
    if not slug:
        print("could not determine OWNER/REPO from the repository remote", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        resolved = resolve_profile(
            registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs
        )
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # R3-7/§2.6: complete-protection applies the resolved profile's protected settings to a PINNED
    # consumer, so an incompatible local tool must not silently mutate them — gate on version-pin
    # compatibility exactly like sync/drift-report/scan-fix (with the same --override escape hatch).
    pin_error = _version_pin_error(root, declaration, expected, getattr(args, "override_version_pin", False))
    if pin_error:
        print(pin_error, file=sys.stderr)
        return 2

    desired = _desired_settings(resolved)
    try:
        skipped = GitHubPlatform().apply_settings(slug, desired)
    except UnmodeledProtectionError as exc:
        # The live protection surface carries something this reconcile cannot safely write
        # (unmodeled classic protection, or ruleset-owned branch protection). Fail closed with
        # a clean operator error, never a traceback (§2.4/§5.7) — mirrors cmd_reconcile.
        print(f"complete-protection aborted (fail-closed): {exc}", file=sys.stderr)
        return 1
    except (GitHubAPIError, CommandError) as exc:
        print(f"error applying protection: {exc}", file=sys.stderr)
        return 1
    print(f"applied full protection to {slug} (idempotent, §5.2 complete-protection).")
    if skipped:
        # R2-4-3: a requested §17 toggle was surfaced-and-skipped (feature unavailable). Branch
        # protection landed; do not let the success line imply the security toggle did too.
        print(
            f"NOTE: security toggle(s) SKIPPED (unavailable on the repo — enable per §17, then "
            f"re-run): {sorted(skipped)}",
            file=sys.stderr,
        )
    return 0


def cmd_provision(args: argparse.Namespace) -> int:
    """Provision a NEW repository with staged protection (§5.2 provision-new / §2.11).

    create repo (README-initialized) → MINIMAL protection → clone + write declaration +
    scaffold + first commit + direct push → FULL protection. If full protection fails
    the repo is left in the partially-provisioned state and the operator is pointed at
    the idempotent `complete-protection` recovery (§8.7). Operator-DIRECT (§2.3).
    """
    slug = args.slug
    if "/" not in slug:
        print("provide the new repository as OWNER/REPO", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        # Canonicalize the pin to bare SemVer (§6.1) before it lands in the declaration
        # or markers; a legacy ``v`` is stripped and a malformed pin is refused.
        if args.pin is None:
            raise DeclarationError(
                "provision requires --pin (X.Y.Z or N) so generated workflows reference a published "
                "Aviato Library ref (§6.1)."
            )
        args.pin = normalize_pin(args.pin)
        _require_published_pin(args.pin, allow_unresolved=args.allow_unresolved_pin)
        resolved = resolve_profile(registry, args.profile, docs=args.docs)
        variables = resolve_variables(
            resolved.variables,
            flags=_parse_var_flags(args.var),
            declaration={},
            env=_env_vars(resolved.variables),
            # §5.2 day-zero: see _autodetect_vars — provision KNOWS the owner (the slug
            # argument's owner half), so it is read, not guessed (finding 28).
            autodetect={"owner": slug.split("/", 1)[0]},
        )
        persisted = writeback_variables(resolved.variables, variables)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    declaration = Declaration(profile=args.profile, version=args.pin, docs=args.docs, variables=persisted)
    desired = _desired_settings(resolved)
    items = materialize_items(registry, args.profile, variables, pin=args.pin, docs=args.docs)

    def scaffold_push() -> None:
        # Local side effects only (kept out of core): clone the just-created repo,
        # write the declaration + scaffold managed files, commit, and push DIRECTLY to
        # the default branch — allowed because minimal protection has no PR gate (§2.11).
        workdir = Path(tempfile.mkdtemp(prefix="aviato-provision-"))
        atexit.register(shutil.rmtree, workdir, True)  # clean the clone at exit (one command per process)
        clone = workdir / "repo"
        run(["gh", "repo", "clone", slug, str(clone)])
        decl_path = clone / ".github" / "aviato.yaml"
        decl_path.parent.mkdir(parents=True, exist_ok=True)
        dump_declaration(declaration, decl_path)
        scaffold(clone, items, profile=args.profile, version=args.pin)
        run(["git", "-C", str(clone), "config", "user.name", "aviato-bot"])
        run(["git", "-C", str(clone), "config", "user.email", "aviato-bot@users.noreply.github.com"])
        run(["git", "-C", str(clone), "add", "-A"])
        # Disable commit signing for this automated bot commit: it must not depend on the
        # operator's GPG/SSH signing identity (a global commit.gpgsign would otherwise fail).
        run(
            [
                "git",
                "-C",
                str(clone),
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "chore: adopt Aviato conventions (§5.2)",
            ]
        )
        run(["git", "-C", str(clone), "push", "origin", "HEAD"])

    try:
        outcome = provision_repo(
            GitHubPlatform(), repo=slug, desired=desired, private=not args.public, scaffold_push=scaffold_push
        )
    except (GitHubAPIError, CommandError) as exc:
        # Reached only if create_repo itself failed (nothing was created); post-create failures
        # are returned as a partial outcome below, never raised (§8.7).
        print(f"provisioning failed before the repository was created: {exc}", file=sys.stderr)
        return 1

    if not outcome.minimal_applied:
        # The repo was CREATED but minimal protection could not be applied — it now EXISTS and
        # is UNPROTECTED. Never leave that silent (§8.7): point at the idempotent recovery.
        print(
            f"created {slug}, but FAILED to apply protection ({outcome.reason}). The repository "
            f"EXISTS and is currently UNPROTECTED (§8.7). Protect it now with:\n"
            f"    aviato complete-protection <local-clone-of-{slug}>\n"
            f"(full protection requires a PR, so push the scaffold via one afterward), or delete "
            f"the repository and retry.",
            file=sys.stderr,
        )
        return 1

    if not outcome.scaffolded:
        # Minimal protection persists (no force-push/deletion), so the repo is NOT unprotected;
        # the scaffold push failed before full protection. Recoverable, not an exposure.
        print(
            f"created {slug}; minimal protection applied; but the scaffold push FAILED "
            f"({outcome.reason}). Minimal protection (no force-push/deletion) persists, so the "
            f"repo is not unprotected. Re-run provisioning, or scaffold + push manually then "
            f"`aviato complete-protection <local-clone-of-{slug}>`.",
            file=sys.stderr,
        )
        return 1

    print(f"created {slug} (private={not args.public}); minimal protection applied; scaffold pushed.")
    if outcome.partial:
        print(
            f"PARTIAL: full protection failed ({outcome.reason}). The repo is in the "
            f"partially-provisioned state (minimal protection persists). Recover with:\n"
            f"    aviato complete-protection <local-clone-of-{slug}>",
            file=sys.stderr,
        )
        return 1
    print(f"applied full protection to {slug}. Provisioned (§5.2).")
    if outcome.skipped_security:
        # R2-1-PROV: a requested §17 toggle was surfaced-and-skipped (feature unavailable). Full
        # branch protection landed, but do not let the success line imply the security toggle did.
        print(
            f"NOTE: security toggle(s) SKIPPED (unavailable on the repo — enable per §17, then "
            f"`aviato complete-protection <local-clone-of-{slug}>`): {sorted(outcome.skipped_security)}",
            file=sys.stderr,
        )
    return 0


SETTINGS_DRIFT_ISSUE_KEY = "aviato-settings-drift"


def cmd_drift_report(args: argparse.Namespace) -> int:
    """Consumer-automation entrypoint: report file + settings drift (§5.5/§5.6).

    Low-privilege, propose/report-only — never mutates protected settings. Run on
    a jittered schedule by the consumer-automation workflow.
    """
    if args.file_only and args.require_settings:
        # --require-settings gates the settings-read skip; with --file-only there is no settings
        # phase to gate, so the combination is a silent no-op. Reject it rather than mislead a CI
        # gate into thinking it enforces a settings read (§5.6).
        print("--require-settings has no effect with --file-only (there is no settings drift to gate)", file=sys.stderr)
        return 2

    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    slug = normalize_slug(remote_url(root))
    if not slug:
        print("could not determine OWNER/REPO from the repository remote", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        resolved = resolve_profile(
            registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs
        )
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pin_error = _version_pin_error(root, declaration, expected, args.override_version_pin)
    if pin_error:
        print(pin_error, file=sys.stderr)
        return 2

    # §11.2/§5.6 least-privilege: file drift and settings drift use DIFFERENT privileges
    # (contents/PR/issue write vs. the admin `administration` read). The consumer-automation
    # workflow runs them as separate steps under separate tokens, so --file-only / --settings-
    # only let each step carry only the token it needs; the default runs both (operator/local).
    do_file = not args.settings_only
    do_settings = not args.file_only
    platform = GitHubPlatform(workdir=root)
    rc = 0  # R3-3: a file-drift channel failure sets rc=1 but must NOT abort the settings phase

    if do_file:
        secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
        # diagnose() rejects a bootstrap declaration in a non-Library repo (§5.4/§5.10) — surface
        # that as a clean operator error (exit 2), not an uncaught traceback.
        try:
            report = diagnose(
                root,
                expected,
                declaration_variables=declaration.variables,
                secret_var_names=secret_names,
                profile=declaration.profile,
                is_library=is_library(root),
                bootstrap_declared=declaration.bootstrap,
            )
        except AviatoError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        # The proposal must write the SAME marker-stamped content scaffold() writes, so
        # a merged PR is classified clean (not dirty for a missing marker, §6.2/§5.4).
        managed_bodies: dict[str, str] = {}
        for artifact in resolved_artifacts(
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
            bootstrap=declaration.bootstrap,
            overrides=declaration.overrides,
        ):
            if artifact.seed_once:
                continue
            item = ScaffoldItem(output=artifact.output, body=artifact.body, comment=artifact.comment)
            managed_bodies[artifact.output] = render_managed(
                item, profile=declaration.profile, version=declaration.version
            )

        # R3-3/§5.6: a file-drift proposal push failure (CommandError/GitHubAPIError) must FAIL
        # LOUD with a non-zero exit but NOT abort before the independent settings-drift phase —
        # the two are deliberately separate steps under separate tokens.
        try:
            file_outcome = run_file_drift(
                platform,
                repo=slug,
                profile=declaration.profile,
                statuses=report.statuses,
                expected_bodies=managed_bodies,
                # Bootstrap (§2.10/§5.10): when the Library diagnoses itself it does not raise
                # file-drift proposals against the remote-ref scaffold — its automation is
                # self-applied/operator-maintained locally. Consistent with the pin-gate skip.
                is_bootstrap=is_library(root),
            )
            print(f"file drift: proposed={file_outcome.proposed} dirty={file_outcome.dirty}")
        except (GitHubAPIError, CommandError) as exc:
            print(f"file drift: FAILED — could not open/update the proposal ({exc})", file=sys.stderr)
            rc = 1

    # Settings drift READS branch protection / rulesets, which the platform GITHUB_TOKEN
    # cannot do (it has no administration scope). §5.6 splits two failure modes that must
    # NOT be conflated:
    #   - a live-settings READ failure (no admin token) → skip fail-closed (never compute
    #     from a falsely-unprotected read, §2.7); by default exits 0 so a scheduled run is
    #     not failed by a missing token (--require-settings makes the skip fail);
    #   - an ISSUE-CHANNEL failure (issues disabled / API error opening or commenting the
    #     tracking issue) → FAIL LOUD (§5.6 "never silently drops the report"), exit non-zero.
    if do_settings:
        try:
            # CX#1: pass the consumer's resolved required_reviews override so the ruleset render
            # matches the classic-protection desired state (both express the same approval count).
            _db = resolved.settings.get("default_branch", {})
            drifted_rulesets = _drifted_rulesets(
                slug,
                platform,
                required_approvals=_db.get("required_reviews"),
                extra_status_checks=list(_db.get("required_status_checks", [])),
            )
            settings_outcome = run_settings_drift(
                platform,
                repo=slug,
                desired_settings=_desired_settings(resolved),
                issue_key=SETTINGS_DRIFT_ISSUE_KEY,
                drifted_rulesets=drifted_rulesets,
                profile=declaration.profile,
                # C12-3: the issue-body remediation points at apply-rulesets --declaration so the
                # restored ruleset honours this consumer's overrides (the standard consumer path).
                declaration_path=".github/aviato.yaml",
            )
            print(f"settings drift: {settings_outcome.status} (destructive={settings_outcome.destructive})")
            if settings_outcome.drifted_rulesets:
                print(
                    f"  missing/drifted rulesets (apply with `aviato apply-rulesets {slug} "
                    # finding 26: the REPO-RELATIVE declaration path (the runner-local
                    # absolute path printed here before does not exist on the operator's
                    # machine; the issue body already used the relative form).
                    f"--apply --declaration .github/aviato.yaml`): {list(settings_outcome.drifted_rulesets)}"
                )
        except SettingsReadError as exc:
            print(
                f"settings drift: skipped — could not read protected settings ({exc}); "
                "supply an admin-capable `settings-token` secret to enable it (§5.6).",
                file=sys.stderr,
            )
            if args.require_settings:
                return 1
        except (GitHubAPIError, CommandError) as exc:
            # The issue channel (not the settings read) failed. §5.6 requires this to fail loud —
            # never a silent skip — so §5.4 diagnosis can flag the broken channel. N5: the issue
            # WRITE (open_or_update_issue → gh) raises CommandError, not GitHubAPIError, so without
            # catching it the failure fell through to main()'s exit 2 instead of this fail-loud exit 1.
            print(
                f"settings drift: FAILED — the tracking-issue channel is unavailable ({exc}); "
                "the drift report was not delivered (§5.6). This is not a settings-read skip.",
                file=sys.stderr,
            )
            return 1
    return rc


def cmd_lint_actions(args: argparse.Namespace) -> int:
    """Report §11.3 supply-chain pin violations (unpinned uses/images, unchecked fetch-execute,
    non-exact pip pins, unpinned npx registry fetches); exit 1 on any. (R10-7: the rows span several
    check classes, so the message is generic — not just 'unpinned action'.)"""
    from .plugins.actionpins import action_pin_violations

    violations = action_pin_violations(Path(args.path))
    for violation in violations:
        print(f"§11.3 supply-chain violation: {violation}", file=sys.stderr)
    if violations:
        print(
            f"{len(violations)} §11.3 supply-chain violation(s): pin third-party `uses:`/images by "
            f"digest, checksum-verify any fetched-and-executed download, pin pip tools to an exact "
            f"version, and pin npx registry tools to an exact version or --no-install (Dependabot "
            f"keeps digests current).",
            file=sys.stderr,
        )
        return 1
    print("Supply-chain pins OK: actions/images digest-pinned, no unchecked fetch-execute.")
    return 0


def cmd_is_highest(args: argparse.Namespace) -> int:
    """Exit 0 iff CANDIDATE is the highest released version (§8.14 monotonic alias guard)."""
    from .core.versioning import _release_key

    # review #28: exit 1 is fail-closed for BOTH "not highest" and "unparseable candidate"; emit a
    # stderr note in the unparseable case so an operator debugging a workflow can tell a malformed
    # tag from a genuinely-older one (the gate behavior is unchanged — still exit 1).
    if _release_key(args.candidate) is None:
        print(
            f"is-highest: candidate {args.candidate!r} is not a parseable version (treated as not highest)",
            file=sys.stderr,
        )
    return 0 if is_highest(args.candidate, args.existing) else 1


def cmd_next_version(args: argparse.Namespace) -> int:
    """Derive the next SemVer from Conventional Commits (§5.9).

    Commit messages come from --commit (repeatable) or, failing that, stdin
    (NUL-separated, e.g. `git log --format=%B%x00`).
    """
    commits = list(args.commit or [])
    if not commits:
        raw = sys.stdin.read()
        commits = [c for c in (raw.split("\0") if "\0" in raw else raw.split("\n\n")) if c.strip()]
    try:
        result = next_version(args.current, classify_commits(commits))
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(result)
    return 0


def cmd_bump_version(args: argparse.Namespace) -> int:
    """Write a new version into the profile's version-source locations (§3.3/§5.9)."""
    # finding 21 (+ second-review fix): refuse a malformed version BEFORE writing — a
    # garbage value would be spliced into manifests and reported as success. Gate on
    # the RELEASE grammar (prereleases are policy-valid bump targets; leading zeros
    # are not, finding 47; a bare-major pin is a Library ref, not a release version).
    candidate = args.version.strip()
    bare = candidate[1:] if candidate.startswith("v") else candidate
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta)[0-9]+)?", bare):
        print(
            f"not a release version: {args.version!r} (expected X.Y.Z or X.Y.Z-alphaN/-betaN)",
            file=sys.stderr,
        )
        return 2
    args.version = bare
    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2
    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        resolved = resolve_profile(registry, declaration.profile, overrides=declaration.overrides)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    locations = list(resolved.version_source.locations) if resolved.version_source else []
    if not locations:
        print("profile declares no version-source locations", file=sys.stderr)
        return 2
    present = [loc for loc in locations if (root / loc).is_file()]
    try:
        changed = bump_files(root, locations, args.version, args.build_number)
    except AviatoError as exc:
        # R4-2-BUMP: a non-UTF-8 version-source fails closed (clean error + exit 1), never a
        # misleading "nothing to bump" success nor a raw traceback.
        print(str(exc), file=sys.stderr)
        return 1
    for location in changed:
        print(f"bumped {location} -> {args.version}")
    if not present:
        # No version-source file exists on disk at all — flag it and NAME the expected locations
        # so the operator can override `version_source.locations` for their real layout (e.g. a
        # Swift repo's Xcode project lives at <Scheme>.xcodeproj/project.pbxproj, not the day-zero
        # placeholder paths). §3.3/§12.3/§13.4.6.
        print(
            f"no version-source file found among {locations}; set `overrides` / the profile's "
            "version_source.locations to your project's actual version file(s).",
            file=sys.stderr,
        )
        return 1
    if not changed:
        # Files exist but are already at the target: a successful idempotent no-op (§2.5),
        # not a failure — re-running a release/bump must not error.
        print(f"version-source already at {args.version}; nothing to bump")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        print(f"no declaration at {declaration_path}", file=sys.stderr)
        return 2

    slug = normalize_slug(remote_url(root))
    if not slug:
        print("could not determine OWNER/REPO from the repository remote", file=sys.stderr)
        return 2

    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        declaration = load_declaration(declaration_path)
        resolved = resolve_profile(
            registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs
        )
        expected = _expected_artifacts(registry, declaration)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # The §2.6 lower bound comes from the consumer's own managed markers, not the
    # installed tool version (an explicit --recorded-version still overrides). Use the
    # MOST RESTRICTIVE marker (the highest recorded version), not the first — a later
    # marker recording a higher/incompatible version must not hide behind a compatible
    # first one (mirrors the all-markers gate in _version_pin_error).
    recorded_markers = _recorded_versions(root, expected)
    recorded_version = (
        args.recorded_version
        or (most_restrictive_recorded(recorded_markers) if recorded_markers else None)
        or declaration.version
    )

    desired = _desired_settings(resolved)

    try:
        outcome = run_reconcile(
            GitHubPlatform(),
            repo=slug,
            issue_key=args.issue,
            desired_settings=desired,
            pin=declaration.version,
            tool_version=__version__,
            recorded_version=recorded_version,
            confirmed_diff_id=args.confirm,
            override_version_pin=args.override_version_pin,
        )
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1
    except UnmodeledProtectionError as exc:
        # Fail closed: the live protection surface this reconcile cannot safely write
        # (unmodeled classic protection, or branch protection owned by a ruleset). Never
        # report applied — surface the reason and exit non-zero (§2.4/§5.7).
        print(f"reconcile aborted (fail-closed): {exc}", file=sys.stderr)
        return 1
    except CommandError as exc:
        # A raw gh/git write failure during apply (e.g. the wholesale branch-protection PUT)
        # must surface as a clean, fail-closed operator error — not an uncaught traceback. The
        # apply may have PARTIALLY landed; run_reconcile has already left a best-effort audit
        # comment on the issue (§5.7), so report and exit non-zero rather than crash.
        print(f"reconcile failed during apply (a change may have partially landed): {exc}", file=sys.stderr)
        return 1

    # Render the APPLY-TIME recomputed diff (the read that was actually acted on, §2.8),
    # not an earlier preview — so the operator confirms/sees the same content.
    if outcome.changes:
        print(f"Apply-time settings diff (id {outcome.diff_id}):")
        values = outcome.values or {}
        for key, kind in sorted(outcome.changes.items()):
            v = values.get(key, {})
            print(f"  {key}: {kind} ({v.get('live')!r} -> {v.get('desired')!r})")
        if not args.confirm:
            print(f"Re-run with --confirm {outcome.diff_id} to apply this exact diff.", file=sys.stderr)
    else:
        print("No settings drift: live state already matches desired.")

    print(f"{outcome.action}: {outcome.reason}")
    return 0 if outcome.action in {"apply", "noop"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aviato")
    subparsers = parser.add_subparsers(required=True)

    audit = subparsers.add_parser("audit", help="Audit local repositories.")
    audit.add_argument("root", nargs="?", default=os.environ.get("AVIATO_REPO_ROOT", "."))
    audit.add_argument("--repo", action="append", help="Audit one explicit local repository path.")
    audit.add_argument("--format", choices=["tsv", "json"], default="tsv")
    audit.set_defaults(func=cmd_audit)

    apply = subparsers.add_parser("apply-rulesets", help="Create or update GitHub rulesets.")
    apply.add_argument("repo_pos", nargs="*", help="Repository slug, for example OWNER/REPO.")
    apply.add_argument("--repo", action="append", help="Repository slug, for example OWNER/REPO.")
    apply.add_argument("--repos-file", help="Optional newline-delimited list of repository slugs.")
    apply.add_argument("--apply", action="store_true", help="Apply changes instead of dry-running.")
    apply.add_argument(
        "--required-approvals", type=_non_negative_int, help="Override required PR approval count (>= 0)."
    )
    # C12-3: --profile (base) and --declaration (override-aware) are mutually exclusive — passing both
    # silently let the declaration win, which is a confusing footgun. argparse now rejects both.
    apply_source = apply.add_mutually_exclusive_group()
    apply_source.add_argument(
        "--profile",
        help="Inject the profile's language verify status checks (e.g. ci / Python CI) into the branch ruleset.",
    )
    apply_source.add_argument(
        "--declaration",
        help="Path to a consumer .github/aviato.yaml: resolve status checks + approvals WITH its "
        "overrides (C12-3), so a ruleset apply does not re-add a check the consumer removed.",
    )
    apply.set_defaults(func=cmd_apply_rulesets)

    render = subparsers.add_parser("render-rulesets", help="Render configured ruleset payloads.")
    render.add_argument(
        "--required-approvals", type=_non_negative_int, help="Override required PR approval count (>= 0)."
    )
    render.add_argument(
        "--profile",
        help="Inject the profile's language verify status checks into the rendered branch ruleset.",
    )
    render.set_defaults(func=cmd_render_rulesets)

    validate_cmd = subparsers.add_parser("validate", help="Validate Aviato policy infrastructure.")
    validate_cmd.set_defaults(func=cmd_validate)

    onboard = subparsers.add_parser(
        "onboard", help="Print an onboarding plan, or adopt a local repository with --write (§5.2)."
    )
    onboard.add_argument("target", help="Repository path or OWNER/REPO slug.")
    onboard.add_argument("--profile", default="python-service")
    onboard.add_argument("--docs", action="store_true", help="Compose the opt-in docs deploy (§13.3).")
    onboard.add_argument(
        "--write",
        action="store_true",
        help="Adopt a local repo: write .github/aviato.yaml and scaffold managed files.",
    )
    onboard.add_argument(
        "--pin",
        default=None,
        help="Library version pin (X.Y.Z or N) to record. Required for a fresh write/proposal; "
        "for an already-adopted repo the existing pin is preserved (use `aviato "
        "repin` to move it, §5.12).",
    )
    onboard.add_argument(
        "--allow-unresolved-pin",
        action="store_true",
        help="Skip the published-ref check for an intentional offline/test scaffold.",
    )
    onboard.add_argument("--var", action="append", help="Set a declaration variable as KEY=VALUE (repeatable).")
    onboard.add_argument(
        "--migrate-profile", action="store_true", help="Allow changing an already-declared profile (§5.2)."
    )
    onboard.add_argument(
        "--allow-dirty", action="store_true", help="Adopt even if the working tree is not clean (§5.2)."
    )
    onboard.add_argument(
        "--open-pr",
        action="store_true",
        help="Adopt-existing via a proposal: scaffold onto a branch and open a PR (§5.2). "
        "Accepts a local repo path or an OWNER/REPO slug; works in a fresh clone.",
    )
    onboard.set_defaults(func=cmd_onboard)

    doctor = subparsers.add_parser("doctor", help="Diagnose a consumer repository's managed artifacts.")
    doctor.add_argument("path", help="Path to the consumer repository.")
    doctor.add_argument(
        "--no-remote-probe",
        action="store_true",
        help="Skip the GitHub probes for issue-channel availability and scan heartbeat.",
    )
    doctor.set_defaults(func=cmd_doctor)

    sync = subparsers.add_parser("sync", help="Materialize managed artifacts into a consumer repository.")
    sync.add_argument("path", help="Path to the consumer repository.")
    sync.add_argument("--force", action="store_true", help="Overwrite unmanaged/malformed-marker files.")
    sync.add_argument(
        "--override-version-pin", action="store_true", help="Proceed despite a version-pin mismatch (§2.6)."
    )
    sync.set_defaults(func=cmd_sync)

    scan = subparsers.add_parser("scan", help="Diagnose many local consumer repositories (read-only by default).")
    scan.add_argument("paths", nargs="+", help="Consumer repository paths.")
    scan.add_argument(
        "--fix",
        action="store_true",
        help="For each repo with file drift, open a managed-file proposal (§5.11 layered on §5.5).",
    )
    scan.add_argument(
        "--override-version-pin",
        action="store_true",
        help="Proceed with --fix even if this tool is incompatible with a repo's version pin (§2.6).",
    )
    scan.add_argument(
        "--include-archived",
        action="store_true",
        help="Also scan archived repositories (skipped by default, §5.11).",
    )
    scan.add_argument(
        "--audit",
        action="store_true",
        help="Also surface each repo's open settings-drift tracking issue (read-only, §5.11).",
    )
    scan.set_defaults(func=cmd_scan)

    repin = subparsers.add_parser("repin", help="Move a consumer to a different Library version (§5.12).")
    repin.add_argument("path", help="Path to the consumer repository (or OWNER/REPO with --open-pr).")
    repin.add_argument("version", help="Target Library version pin (X.Y.Z or N).")
    repin.add_argument("--write", action="store_true", help="Write the new pin into the declaration and re-scaffold.")
    repin.add_argument(
        "--open-pr",
        action="store_true",
        help="Open a reviewable re-pin proposal (PR) instead of mutating locally (§5.12).",
    )
    repin.add_argument(
        "--allow-unresolved-pin",
        action="store_true",
        help="Skip the published-ref check (intentional offline/test re-pin only, §6.1).",
    )
    repin.add_argument(
        "--override-version-pin",
        action="store_true",
        help="Proceed despite a §2.6 tool/target version-pin mismatch.",
    )
    repin.set_defaults(func=cmd_repin)

    offboard = subparsers.add_parser("offboard", help="Remove a consumer from Aviato management (§5.13).")
    offboard.add_argument("path", help="Path to the consumer repository.")
    offboard.add_argument(
        "--delete-files",
        action="store_true",
        help="Delete managed files instead of stripping their markers (leaving plain files).",
    )
    offboard.add_argument(
        "--write", action="store_true", help="Perform the removal LOCALLY (default is a dry-run plan)."
    )
    offboard.add_argument(
        "--open-pr",
        action="store_true",
        help="Open a reviewable removal proposal (PR) instead of mutating locally (§5.13).",
    )
    offboard.set_defaults(func=cmd_offboard)

    complete = subparsers.add_parser(
        "complete-protection",
        help="Idempotently (re-)apply full branch protection after onboarding (§5.2 recovery).",
    )
    complete.add_argument("path", help="Path to the consumer repository.")
    complete.add_argument(
        "--override-version-pin",
        action="store_true",
        help="Proceed despite a version-pin mismatch (§2.6).",
    )
    complete.set_defaults(func=cmd_complete_protection)

    provision = subparsers.add_parser(
        "provision", help="Provision a NEW repository with staged minimal->full protection (§5.2)."
    )
    provision.add_argument("slug", help="New repository as OWNER/REPO.")
    provision.add_argument("--profile", default="python-service")
    provision.add_argument("--docs", action="store_true", help="Compose the opt-in docs deploy (§13.3).")
    provision.add_argument("--pin", default=None, help="Library version pin to record in the declaration.")
    provision.add_argument(
        "--allow-unresolved-pin",
        action="store_true",
        help="Skip the published-ref check for an intentional offline/test scaffold.",
    )
    provision.add_argument("--var", action="append", help="Set a declaration variable as KEY=VALUE (repeatable).")
    provision.add_argument("--public", action="store_true", help="Create a public repo (default: private).")
    provision.set_defaults(func=cmd_provision)

    drift = subparsers.add_parser("drift-report", help="Consumer automation: report file + settings drift (read-only).")
    drift.add_argument("path", help="Path to the consumer repository.")
    drift.add_argument(
        "--override-version-pin", action="store_true", help="Proceed despite a version-pin mismatch (§2.6)."
    )
    drift_scope = drift.add_mutually_exclusive_group()
    drift_scope.add_argument(
        "--file-only",
        action="store_true",
        help="Run only file drift (platform token; no admin settings-token needed, §5.6).",
    )
    drift_scope.add_argument(
        "--settings-only",
        action="store_true",
        help="Run only settings drift (admin settings-token; read-only, §5.6).",
    )
    drift.add_argument(
        "--require-settings",
        action="store_true",
        help=(
            "Exit non-zero if settings drift cannot be evaluated (unreadable settings). Without "
            "this, an unreadable-settings skip exits 0 so a scheduled run is not failed by a "
            "missing admin token; set it when gating CI on settings drift (§5.6)."
        ),
    )
    drift.set_defaults(func=cmd_drift_report)

    highest = subparsers.add_parser(
        "is-highest", help="Exit 0 iff CANDIDATE is the highest released version (§8.14 alias guard)."
    )
    highest.add_argument("candidate", help="The release tag being deployed.")
    highest.add_argument("existing", nargs="*", help="All released tags.")
    highest.set_defaults(func=cmd_is_highest)

    lint_actions = subparsers.add_parser(
        "lint-actions", help="Flag action/tool invocations that violate §11.3 supply-chain pinning."
    )
    lint_actions.add_argument("path", nargs="?", default=".", help="Repository root (default: .).")
    lint_actions.set_defaults(func=cmd_lint_actions)

    nextver = subparsers.add_parser("next-version", help="Derive the next SemVer from Conventional Commits (§5.9).")
    nextver.add_argument("--current", required=True, help="Current version (X.Y.Z; a legacy v-prefix is tolerated).")
    nextver.add_argument("--commit", action="append", help="A commit message (repeatable); else read stdin.")
    nextver.set_defaults(func=cmd_next_version)

    bump = subparsers.add_parser("bump-version", help="Write a version into the version-source locations (§3.3).")
    bump.add_argument("version", help="The new version to write.")
    bump.add_argument("path", help="Path to the consumer repository.")
    bump.add_argument("--build-number", help="Strictly-increasing build number (Swift marketing/build, §13.4).")
    bump.set_defaults(func=cmd_bump_version)

    reconcile = subparsers.add_parser("reconcile", help="Operator-gated settings reconcile against a tracking issue.")
    reconcile.add_argument("path", help="Path to the consumer repository.")
    reconcile.add_argument("issue", help="Tracking-issue key/label.")
    reconcile.add_argument(
        "--confirm",
        metavar="DIFF_ID",
        help="Confirm a specific diff id (from the tracking issue / a prior dry run). The apply "
        "proceeds only if the apply-time recomputed diff still matches this id.",
    )
    reconcile.add_argument("--recorded-version", help="Version recorded in the consumer's markers (§2.6).")
    reconcile.add_argument(
        "--override-version-pin",
        action="store_true",
        help="Proceed despite a version-pin mismatch (§2.6); pairs with --confirm.",
    )
    reconcile.set_defaults(func=cmd_reconcile)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Top-level safety net (review #8): per-command handlers map the EXPECTED error families to
    # specific exit codes (1 vs 2), but the contract is "never leak a raw traceback." If any path
    # forgets to guard an AviatoError/GitHubAPIError/CommandError, fail closed to a clean stderr
    # message + exit 2 instead of a stack trace. (Genuinely unexpected exceptions still propagate
    # — those are bugs we WANT to see, not operator errors.)
    try:
        return int(args.func(args))
    except (AviatoError, GitHubAPIError, CommandError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
