from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .audit import audit_repos, discover_and_audit, render_json, render_tsv
from .command import CommandError, run
from .core.bootstrap import is_library
from .core.composition import resolve_profile
from .core.declaration import Declaration, dump_declaration, load_declaration
from .core.diagnosis import ExpectedArtifact, diagnose
from .core.errors import AviatoError
from .core.file_drift_flow import run_file_drift
from .core.fleet import scan_fleet
from .core.marker import parse_marker_from_text
from .core.offboarding import offboard as offboard_repo
from .core.onboarding import materialize_items, plan_onboarding, resolved_artifacts
from .core.provision import provision_repo
from .core.reconcile_flow import run_reconcile
from .core.registry import Registry
from .core.repin import plan_repin
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
from .repos import git_root, normalize_slug, remote_url, working_tree_clean
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

    items = materialize_items(
        registry, args.profile, variables, pin=args.pin, docs=args.docs, overrides=declaration.overrides
    )
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
            registry,
            declaration.profile,
            declaration.variables,
            pin=declaration.version,
            docs=declaration.docs,
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
    return 0


def _scan_has_file_drift(scan) -> bool:
    # "missing"/"drift" managed-file statuses are fixable by a proposal; "dirty"
    # (operator-owned / malformed marker) is NOT auto-fixed (§5.4/§5.5).
    return any(status in {"missing", "drift"} for status in scan.statuses.values())


def cmd_scan(args: argparse.Namespace) -> int:
    registry = Registry(MODULE_SOURCE_ROOT)
    scans = scan_fleet([Path(p) for p in args.paths], registry)
    rc = 0
    for scan in scans:
        if scan.error:
            print(f"{scan.path}\tERROR: {scan.error}")
            continue
        summary = ", ".join(f"{output}={status}" for output, status in sorted(scan.statuses.items())) or "—"
        flags = " [secret-in-declaration]" if scan.secret_in_declaration else ""
        print(f"{scan.path}\t{scan.profile}\t{summary}{flags}")
        if args.fix and _scan_has_file_drift(scan):
            try:
                outcome = _propose_file_drift(registry, Path(scan.path))
                print(f"  fix: proposed={outcome.proposed} dirty={outcome.dirty}")
            except (AviatoError, GitHubAPIError) as exc:
                print(f"  fix ERROR: {exc}", file=sys.stderr)
                rc = 1
    return rc


def _propose_file_drift(registry: Registry, root: Path):
    """Open a managed-file drift proposal for one repo (§5.5), shared by scan --fix.

    Resolves the repo's declaration, re-diagnoses, and routes the same
    marker-stamped bodies scaffold() would write through ``run_file_drift`` so a
    merged PR classifies clean (§6.2/§5.4).
    """
    declaration_path = root / ".github" / "aviato.yaml"
    if not declaration_path.is_file():
        raise AviatoError(f"no declaration at {declaration_path}")
    slug = normalize_slug(remote_url(root))
    if not slug:
        raise AviatoError("could not determine OWNER/REPO from the repository remote")

    declaration = load_declaration(declaration_path)
    expected = _expected_artifacts(registry, declaration)
    resolved = resolve_profile(registry, declaration.profile, overrides=declaration.overrides, docs=declaration.docs)
    secret_names = tuple(spec.name for spec in resolved.variables if spec.secret)
    report = diagnose(root, expected, declaration_variables=declaration.variables, secret_var_names=secret_names)

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

    return run_file_drift(
        GitHubPlatform(workdir=root),
        repo=slug,
        profile=declaration.profile,
        statuses=report.statuses,
        expected_bodies=managed_bodies,
    )


def cmd_repin(args: argparse.Namespace) -> int:
    """Move a consumer to a different Library version (§5.12) — the only sanctioned pin move."""
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
    if not plan.ok:
        print("re-pin blocked: supply the newly-required variables first.", file=sys.stderr)
        return 1

    if not args.write:
        print("dry run; re-run with --write to record the new pin and re-scaffold.")
        return 0

    updated = Declaration(
        profile=declaration.profile,
        version=plan.target_version,
        docs=declaration.docs,
        variables=declaration.variables,
        overrides=declaration.overrides,
    )
    dump_declaration(updated, declaration_path)
    print(f"wrote pin {plan.target_version} to {declaration_path.relative_to(root)}")
    items = materialize_items(
        registry,
        updated.profile,
        updated.variables,
        pin=updated.version,
        docs=updated.docs,
        overrides=updated.overrides,
    )
    result = scaffold(root, items, profile=updated.profile, version=updated.version)
    for output in result.written:
        print(f"rewrote {output}")
    print("next: review the re-pinned artifacts, commit on a branch, and open a PR (§5.2/§5.12).")
    return 0


def cmd_offboard(args: argparse.Namespace) -> int:
    """Remove a consumer from Aviato management (§5.13)."""
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

        verb = "delete" if args.delete_files else "strip markers from"
        print(f"dry run; would {verb} {len(managed_outputs)} managed file(s), then remove the declaration + sidecar.")
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
    except AviatoError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    desired = _desired_settings(resolved)
    try:
        GitHubPlatform().apply_settings(slug, desired)
    except GitHubAPIError as exc:
        print(f"GitHub API error applying protection: {exc}", file=sys.stderr)
        return 1
    print(f"applied full protection to {slug} (idempotent, §5.2 complete-protection).")
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
        resolved = resolve_profile(registry, args.profile, docs=args.docs)
        variables = resolve_variables(
            resolved.variables,
            flags=_parse_var_flags(args.var),
            declaration={},
            env=_env_vars(resolved.variables),
            autodetect={},
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
        print(f"provisioning failed before full protection: {exc}", file=sys.stderr)
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
    onboard.add_argument(
        "--allow-dirty", action="store_true", help="Adopt even if the working tree is not clean (§5.2)."
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
    scan.set_defaults(func=cmd_scan)

    repin = subparsers.add_parser("repin", help="Move a consumer to a different Library version (§5.12).")
    repin.add_argument("path", help="Path to the consumer repository.")
    repin.add_argument("version", help="Target Library version pin (vX.Y.Z or vX).")
    repin.add_argument("--write", action="store_true", help="Write the new pin into the declaration and re-scaffold.")
    repin.set_defaults(func=cmd_repin)

    offboard = subparsers.add_parser("offboard", help="Remove a consumer from Aviato management (§5.13).")
    offboard.add_argument("path", help="Path to the consumer repository.")
    offboard.add_argument(
        "--delete-files",
        action="store_true",
        help="Delete managed files instead of stripping their markers (leaving plain files).",
    )
    offboard.add_argument("--write", action="store_true", help="Perform the removal (default is a dry-run plan).")
    offboard.set_defaults(func=cmd_offboard)

    complete = subparsers.add_parser(
        "complete-protection",
        help="Idempotently (re-)apply full branch protection after onboarding (§5.2 recovery).",
    )
    complete.add_argument("path", help="Path to the consumer repository.")
    complete.set_defaults(func=cmd_complete_protection)

    provision = subparsers.add_parser(
        "provision", help="Provision a NEW repository with staged minimal->full protection (§5.2)."
    )
    provision.add_argument("slug", help="New repository as OWNER/REPO.")
    provision.add_argument("--profile", default="python-service")
    provision.add_argument("--docs", action="store_true", help="Compose the opt-in docs deploy (§13.3).")
    provision.add_argument("--pin", default="v0", help="Library version pin to record in the declaration.")
    provision.add_argument("--var", action="append", help="Set a declaration variable as KEY=VALUE (repeatable).")
    provision.add_argument("--public", action="store_true", help="Create a public repo (default: private).")
    provision.set_defaults(func=cmd_provision)

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
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
