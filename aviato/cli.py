from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .audit import audit_repos, discover_and_audit, render_json, render_tsv
from .core.composition import resolve_profile
from .core.declaration import load_declaration
from .core.diagnosis import ExpectedArtifact, diagnose
from .core.errors import AviatoError
from .core.file_drift_flow import run_file_drift
from .core.fleet import scan_fleet
from .core.onboarding import materialize_items
from .core.reconcile_flow import run_reconcile
from .core.registry import Registry
from .core.render import render
from .core.scaffold import scaffold
from .core.settings_drift_flow import run_settings_drift
from .core.versioning import is_highest
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


def cmd_apply_rulesets(args: argparse.Namespace) -> int:
    slugs = list(args.repo_pos)
    slugs.extend(args.repo or [])
    if args.repos_file:
        slugs.extend(_read_repos_file(Path(args.repos_file)))

    if not slugs:
        print("at least one repository slug is required", file=sys.stderr)
        return 2

    try:
        for message in apply_rulesets(slugs, apply=args.apply, required_approvals=args.required_approvals):
            print(message)
        return 0
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1


def cmd_render_rulesets(args: argparse.Namespace) -> int:
    import json

    payloads = render_all_rulesets(required_approvals=args.required_approvals)
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


def _expected_artifacts(registry: Registry, resolved, variables: dict) -> list[ExpectedArtifact]:
    artifacts: list[ExpectedArtifact] = []
    for template in resolved.templates:
        body = registry.template_body(template)
        rendered = "" if template.seed_once else render(body, variables)
        artifacts.append(ExpectedArtifact(template.output_path, rendered, template.seed_once))
    return artifacts


def cmd_onboard(args: argparse.Namespace) -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    try:
        resolved = resolve_profile(registry, args.profile, docs=args.docs)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

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
        expected = _expected_artifacts(registry, resolved, declaration.variables)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    report = diagnose(
        root,
        expected,
        declaration_variables=declaration.variables,
        secret_var_names=secret_names,
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
        items = materialize_items(registry, declaration.profile, declaration.variables)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
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
        expected = _expected_artifacts(registry, resolved, declaration.variables)
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    report = diagnose(root, expected, declaration_variables=declaration.variables, secret_var_names=secret_names)
    expected_bodies = {artifact.output_path: artifact.body for artifact in expected if not artifact.seed_once}

    platform = GitHubPlatform(workdir=root)
    file_outcome = run_file_drift(
        platform,
        repo=slug,
        profile=declaration.profile,
        statuses=report.statuses,
        expected_bodies=expected_bodies,
    )
    settings_outcome = run_settings_drift(
        platform,
        repo=slug,
        desired_settings=resolved.settings.get("default_branch", {}),
        issue_key=SETTINGS_DRIFT_ISSUE_KEY,
    )
    print(f"file drift: proposed={file_outcome.proposed} dirty={file_outcome.dirty}")
    print(f"settings drift: {settings_outcome.status} (destructive={settings_outcome.destructive})")
    return 0


def cmd_is_highest(args: argparse.Namespace) -> int:
    """Exit 0 iff CANDIDATE is the highest released version (§8.14 monotonic alias guard)."""
    return 0 if is_highest(args.candidate, args.existing) else 1


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
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    desired = resolved.settings.get("default_branch", {})
    outcome = run_reconcile(
        GitHubPlatform(),
        repo=slug,
        issue_key=args.issue,
        desired_settings=desired,
        pin=declaration.version,
        tool_version=__version__,
        recorded_version=args.recorded_version or __version__,
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
    apply.set_defaults(func=cmd_apply_rulesets)

    render = subparsers.add_parser("render-rulesets", help="Render configured ruleset payloads.")
    render.add_argument("--required-approvals", type=int, help="Override required PR approval count.")
    render.set_defaults(func=cmd_render_rulesets)

    validate_cmd = subparsers.add_parser("validate", help="Validate Aviato policy infrastructure.")
    validate_cmd.set_defaults(func=cmd_validate)

    onboard = subparsers.add_parser("onboard", help="Print an onboarding plan for one repository.")
    onboard.add_argument("target", help="Repository path or OWNER/REPO slug.")
    onboard.add_argument("--profile", default="python-service")
    onboard.add_argument("--docs", action="store_true", help="Compose the opt-in docs deploy (§13.3).")
    onboard.set_defaults(func=cmd_onboard)

    doctor = subparsers.add_parser("doctor", help="Diagnose a consumer repository's managed artifacts.")
    doctor.add_argument("path", help="Path to the consumer repository.")
    doctor.set_defaults(func=cmd_doctor)

    sync = subparsers.add_parser("sync", help="Materialize managed artifacts into a consumer repository.")
    sync.add_argument("path", help="Path to the consumer repository.")
    sync.add_argument("--force", action="store_true", help="Overwrite unmanaged/malformed-marker files.")
    sync.set_defaults(func=cmd_sync)

    scan = subparsers.add_parser("scan", help="Diagnose many local consumer repositories (read-only).")
    scan.add_argument("paths", nargs="+", help="Consumer repository paths.")
    scan.set_defaults(func=cmd_scan)

    drift = subparsers.add_parser("drift-report", help="Consumer automation: report file + settings drift (read-only).")
    drift.add_argument("path", help="Path to the consumer repository.")
    drift.set_defaults(func=cmd_drift_report)

    highest = subparsers.add_parser(
        "is-highest", help="Exit 0 iff CANDIDATE is the highest released version (§8.14 alias guard)."
    )
    highest.add_argument("candidate", help="The release tag being deployed.")
    highest.add_argument("existing", nargs="*", help="All released tags.")
    highest.set_defaults(func=cmd_is_highest)

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
