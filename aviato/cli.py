from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .audit import audit_repos, discover_and_audit, render_json, render_tsv
from .github import GitHubAPIError
from .paths import REPO_ROOT
from .policy import load_policy
from .profiles import profile_plan
from .repos import git_root
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


def cmd_onboard(args: argparse.Namespace) -> int:
    try:
        plan = profile_plan(args.profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Onboarding plan for {args.target}")
    print(f"profile: {plan.name}")
    print("templates:")
    for template in plan.templates:
        print(f"- {template}")

    if plan.environments:
        print("environments:")
        for environment in plan.environments:
            print(f"- {environment}")

    if plan.secrets:
        print("secrets:")
        for secret in plan.secrets:
            print(f"- {secret}")

    if plan.notes:
        print("notes:")
        for note in plan.notes:
            print(f"- {note}")

    print("rulesets:")
    print("- Common: protect default branch")
    print("- Common: release tag format")
    print("next command:")
    print("aviato apply-rulesets OWNER/REPO --apply")
    return 0


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
    onboard.set_defaults(func=cmd_onboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
