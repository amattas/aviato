from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .audit import audit_repos, discover_and_audit, render_json, render_tsv
from .core.bootstrap import is_library
from .core.composition import resolve_profile
from .core.declaration import Declaration, dump_declaration, load_declaration
from .core.diagnosis import ExpectedArtifact, diagnose
from .core.errors import AviatoError
from .core.file_drift_flow import run_file_drift
from .core.fleet import scan_fleet
from .core.marker import parse_marker_from_text
from .core.onboarding import materialize_items, plan_onboarding, resolved_artifacts
from .core.reconcile_flow import run_reconcile
from .core.registry import Registry
from .core.scaffold import ScaffoldItem, render_managed, scaffold
from .core.settings_drift_flow import run_settings_drift
from .core.variables import resolve_variables, writeback_variables
from .core.version import is_compatible
from .core.versioning import classify_commits, is_highest, next_version
from .core.versionsource import bump_files
from .github import GitHubAPIError
from .github_platform import GitHubPlatform
from .paths import MODULE_SOURCE_ROOT, REPO_ROOT
from .policy import load_policy
from .repos import git_root, normalize_slug, remote_url
from .rulesets import apply_rulesets, render_all_rulesets
from .validation import validate


def _read_repos_file(path: Path) -> list[str]:
    repos: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            repos.append(value)
    return repos


def cmd_audit(args: argparse.Namespace) -> int:
    policy = load_policy(REPO_ROOT)
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


def _profile_status_checks(profile: str | None) -> list[str]:
    """The resolved profile's required status-check contexts (§10), or [] if none.

    Lets `apply-rulesets`/`render-rulesets` inject the language verify job (e.g.
    `ci / Python CI`) into the otherwise-static branch ruleset so it matches the
    profile composed for the repo.
    """
    if not profile:
        return []
    from .core.composition import resolve_profile
    from .core.registry import Registry
    from .paths import MODULE_SOURCE_ROOT

    resolved = resolve_profile(Registry(MODULE_SOURCE_ROOT), profile)
    return list(resolved.settings.get("default_branch", {}).get("required_status_checks", []))


def cmd_apply_rulesets(args: argparse.Namespace) -> int:
    slugs = list(args.repo_pos)
    slugs.extend(args.repo or [])
    if args.repos_file:
        slugs.extend(_read_repos_file(Path(args.repos_file)))

    if not slugs:
        print("at least one repository slug is required", file=sys.stderr)
        return 2

    try:
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
            required_approvals=args.required_approvals,
            extra_status_checks=extra_checks,
        ):
            print(message)
        return 0
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1


def cmd_render_rulesets(args: argparse.Namespace) -> int:
    import json

    try:
        extra_checks = _profile_status_checks(getattr(args, "profile", None))
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payloads = render_all_rulesets(required_approvals=args.required_approvals, extra_status_checks=extra_checks)
    print(json.dumps(payloads, indent=2))
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    errors = validate(REPO_ROOT)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Aviato validation passed.")
    return 0


def _recorded_version(root: Path, expected: list[ExpectedArtifact]) -> str | None:
    """Return the version recorded in the consumer's managed markers, if any (§2.6)."""
    for artifact in expected:
        if artifact.seed_once:
            continue
        path = root / artifact.output_path
        if path.is_file():
            info = parse_marker_from_text(path.read_text(encoding="utf-8"))
            if info is not None:
                return info.version
    return None


def _version_pin_error(
    root: Path, declaration: Declaration, expected: list[ExpectedArtifact], override: bool
) -> str | None:
    """Enforce §2.6 version-pin compatibility before a write/proposal; None if OK.

    Skipped in bootstrap (the Library resolves self-references locally, §2.10/§5.10).
    Refuses on a mismatch unless ``override`` is set.
    """
    if override or is_library(root):
        return None
    recorded = _recorded_version(root, expected) or declaration.version
    if is_compatible(tool=__version__, pinned=declaration.version, recorded=recorded):
        return None
    return (
        f"version-pin mismatch: tool {__version__} is incompatible with pin "
        f"{declaration.version!r} (recorded {recorded!r}); pass --override-version-pin to proceed"
    )


def _tri(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def _desired_settings(resolved) -> dict:
    """Flat reconcilable settings: branch protection + repo security toggles (§5.6/§2.13).

    Rulesets are applied separately (`apply-rulesets`) and are not part of the
    branch-protection/security reconcile diff.
    """
    return {
        **resolved.settings.get("default_branch", {}),
        **resolved.settings.get("security", {}),
    }


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
            overrides=declaration.overrides,
        )
    ]


def _parse_var_flags(pairs: list[str] | None) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise AviatoError(f"--var expects KEY=VALUE, got {pair!r}")
        resolved[key.strip()] = value
    return resolved


def _env_vars(specs) -> dict[str, str]:
    env: dict[str, str] = {}
    for spec in specs:
        key = "AVIATO_VAR_" + spec.name.upper().replace("-", "_")
        if key in os.environ:
            env[spec.name] = os.environ[key]
    return env


def _onboard_write(args: argparse.Namespace, registry: Registry, resolved) -> int:
    """Adopt a local repository (§5.2): resolve variables, write the declaration, scaffold."""
    target = Path(args.target)
    if not target.is_dir():
        print(f"--write requires a local repository path; {args.target!r} is not a directory", file=sys.stderr)
        return 2

    declaration_path = target / ".github" / "aviato.yaml"
    existing = load_declaration(declaration_path) if declaration_path.is_file() else None

    try:
        flags = _parse_var_flags(args.var)
        variables = resolve_variables(
            resolved.variables,
            flags=flags,
            declaration=(existing.variables if existing else {}),
            env=_env_vars(resolved.variables),
            autodetect={},
        )
        plan_onboarding(
            registry,
            profile=args.profile,
            existing_declaration=existing,
            variables=variables,
            allow_migrate=args.migrate_profile,
        )
        persisted = writeback_variables(resolved.variables, variables)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    declaration = Declaration(
        profile=args.profile,
        version=args.pin,
        docs=args.docs,
        variables=persisted,
        overrides=(existing.overrides if existing else {}),
    )
    declaration_path.parent.mkdir(parents=True, exist_ok=True)
    dump_declaration(declaration, declaration_path)
    print(f"wrote {declaration_path.relative_to(target)}")

    items = materialize_items(registry, args.profile, variables, pin=args.pin, docs=args.docs)
    result = scaffold(target, items, profile=args.profile, version=args.pin)
    for output in result.written:
        print(f"wrote {output}")
    for output in result.seeded:
        print(f"seeded {output}")
    for output in result.skipped_unmanaged + result.skipped_modified:
        print(f"SKIPPED (operator-owned) {output}")
    print("next: review the changes, then apply protections with `aviato apply-rulesets OWNER/REPO --apply`")
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        resolved = resolve_profile(registry, args.profile, docs=args.docs)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.write:
        return _onboard_write(args, registry, resolved)

    print(f"Onboarding plan for {args.target}")
    print(f"profile: {resolved.profile}")

    print("pipelines:")
    for pipeline in resolved.pipelines:
        print(f"- {pipeline}")

    print("templates:")
    for template in resolved.templates:
        kind = "seed-once" if template.seed_once else "managed"
        print(f"- {template.output_path} ({kind})")

    if resolved.variables:
        print("variables:")
        for variable in resolved.variables:
            secret = ", secret" if variable.secret else ""
            optional = "" if variable.required else ", optional"
            print(f"- {variable.name} ({variable.type}{optional}{secret})")

    print("settings:")
    for ruleset in resolved.settings.get("rulesets", []):
        print(f"- ruleset: {ruleset}")

    print("next command:")
    print(f"aviato apply-rulesets {args.target} --apply")
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
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    prerequisite_paths = registry.profile_doc(declaration.profile).get("prerequisites", {})
    report = diagnose(
        root,
        expected,
        declaration_variables=declaration.variables,
        secret_var_names=secret_names,
        prerequisite_paths=prerequisite_paths,
    )

    # Platform-dependent probes (§5.4/§5.14): issue-channel availability and the
    # per-run scan heartbeat. Best-effort — populated only if a repo slug resolves.
    slug = normalize_slug(remote_url(root))
    if slug and not args.no_remote_probe:
        report.issue_channel_available, report.scan_heartbeat_present = GitHubPlatform().probe_health(slug)

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
            registry, declaration.profile, declaration.variables, pin=declaration.version, docs=declaration.docs
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
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    scans = scan_fleet([Path(p) for p in args.paths], registry)
    for scan in scans:
        if scan.error:
            print(f"{scan.path}\tERROR: {scan.error}")
            continue
        summary = ", ".join(f"{output}={status}" for output, status in sorted(scan.statuses.items())) or "—"
        flags = " [secret-in-declaration]" if scan.secret_in_declaration else ""
        print(f"{scan.path}\t{scan.profile}\t{summary}{flags}")
    return 0


SETTINGS_DRIFT_ISSUE_KEY = "aviato-settings-drift"


def cmd_drift_report(args: argparse.Namespace) -> int:
    """Consumer-automation entrypoint: report file + settings drift (§5.5/§5.6).

    Low-privilege, propose/report-only — never mutates protected settings. Run on
    a jittered schedule by the consumer-automation workflow.
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

    pin_error = _version_pin_error(root, declaration, expected, args.override_version_pin)
    if pin_error:
        print(pin_error, file=sys.stderr)
        return 2

    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    report = diagnose(root, expected, declaration_variables=declaration.variables, secret_var_names=secret_names)

    # The proposal must write the SAME marker-stamped content scaffold() writes, so
    # a merged PR is classified clean (not dirty for a missing marker, §6.2/§5.4).
    managed_bodies: dict[str, str] = {}
    for artifact in resolved_artifacts(
        registry,
        declaration.profile,
        declaration.variables,
        pin=declaration.version,
        docs=declaration.docs,
        overrides=declaration.overrides,
    ):
        if artifact.seed_once:
            continue
        item = ScaffoldItem(output=artifact.output, body=artifact.body, comment=artifact.comment)
        managed_bodies[artifact.output] = render_managed(item, profile=declaration.profile, version=declaration.version)

    platform = GitHubPlatform(workdir=root)
    file_outcome = run_file_drift(
        platform,
        repo=slug,
        profile=declaration.profile,
        statuses=report.statuses,
        expected_bodies=managed_bodies,
    )
    settings_outcome = run_settings_drift(
        platform,
        repo=slug,
        desired_settings=_desired_settings(resolved),
        issue_key=SETTINGS_DRIFT_ISSUE_KEY,
    )
    print(f"file drift: proposed={file_outcome.proposed} dirty={file_outcome.dirty}")
    print(f"settings drift: {settings_outcome.status} (destructive={settings_outcome.destructive})")
    return 0


def cmd_lint_actions(args: argparse.Namespace) -> int:
    """Flag third-party actions not pinned by commit digest (§11.3); exit 1 on any."""
    from .core.actionpins import action_pin_violations

    violations = action_pin_violations(Path(args.path))
    for violation in violations:
        print(f"unpinned third-party action: {violation}", file=sys.stderr)
    if violations:
        print(
            f"{len(violations)} third-party action(s) not pinned to a commit digest (§11.3); "
            f"pin each `uses: owner/repo@<40-hex-sha>` (Dependabot keeps them current).",
            file=sys.stderr,
        )
        return 1
    print("All third-party actions are digest-pinned.")
    return 0


def cmd_is_highest(args: argparse.Namespace) -> int:
    """Exit 0 iff CANDIDATE is the highest released version (§8.14 monotonic alias guard)."""
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
    print(next_version(args.current, classify_commits(commits)))
    return 0


def cmd_bump_version(args: argparse.Namespace) -> int:
    """Write a new version into the profile's version-source locations (§3.3/§5.9)."""
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
    changed = bump_files(root, locations, args.version, args.build_number)
    for location in changed:
        print(f"bumped {location} -> {args.version}")
    if not changed:
        print("no version-source files found to bump", file=sys.stderr)
        return 1
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
    # installed tool version (an explicit --recorded-version still overrides).
    recorded_version = args.recorded_version or _recorded_version(root, expected) or declaration.version

    desired = _desired_settings(resolved)
    outcome = run_reconcile(
        GitHubPlatform(),
        repo=slug,
        issue_key=args.issue,
        desired_settings=desired,
        pin=declaration.version,
        tool_version=__version__,
        recorded_version=recorded_version,
        operator_confirmed=args.confirm,
    )
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
    apply.add_argument("--required-approvals", type=int, help="Override required PR approval count.")
    apply.add_argument(
        "--profile",
        help="Inject the profile's language verify status checks (e.g. ci / Python CI) into the branch ruleset.",
    )
    apply.set_defaults(func=cmd_apply_rulesets)

    render = subparsers.add_parser("render-rulesets", help="Render configured ruleset payloads.")
    render.add_argument("--required-approvals", type=int, help="Override required PR approval count.")
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
    onboard.add_argument("--pin", default="v0", help="Library version pin to record in the declaration.")
    onboard.add_argument("--var", action="append", help="Set a declaration variable as KEY=VALUE (repeatable).")
    onboard.add_argument(
        "--migrate-profile", action="store_true", help="Allow changing an already-declared profile (§5.2)."
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

    scan = subparsers.add_parser("scan", help="Diagnose many local consumer repositories (read-only).")
    scan.add_argument("paths", nargs="+", help="Consumer repository paths.")
    scan.set_defaults(func=cmd_scan)

    drift = subparsers.add_parser("drift-report", help="Consumer automation: report file + settings drift (read-only).")
    drift.add_argument("path", help="Path to the consumer repository.")
    drift.add_argument(
        "--override-version-pin", action="store_true", help="Proceed despite a version-pin mismatch (§2.6)."
    )
    drift.set_defaults(func=cmd_drift_report)

    highest = subparsers.add_parser(
        "is-highest", help="Exit 0 iff CANDIDATE is the highest released version (§8.14 alias guard)."
    )
    highest.add_argument("candidate", help="The release tag being deployed.")
    highest.add_argument("existing", nargs="*", help="All released tags.")
    highest.set_defaults(func=cmd_is_highest)

    lint_actions = subparsers.add_parser(
        "lint-actions", help="Flag third-party actions not pinned by commit digest (§11.3)."
    )
    lint_actions.add_argument("path", nargs="?", default=".", help="Repository root (default: .).")
    lint_actions.set_defaults(func=cmd_lint_actions)

    nextver = subparsers.add_parser("next-version", help="Derive the next SemVer from Conventional Commits (§5.9).")
    nextver.add_argument("--current", required=True, help="Current version (vX.Y.Z or X.Y.Z).")
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
    reconcile.add_argument("--confirm", action="store_true", help="Confirm the apply-time recomputed diff.")
    reconcile.add_argument("--recorded-version", help="Version recorded in the consumer's markers (§2.6).")
    reconcile.set_defaults(func=cmd_reconcile)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
