from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from aviato.cli import main
from aviato.core.registry import Registry

CONSUMER_MODULES = (
    "aviato/cli.py",
    "aviato/rulesets.py",
    "aviato/audit.py",
    "aviato/core/fleet.py",
    "aviato/plugins/actionpins.py",
    "aviato/plugins/zizmor_scan.py",
)

_ROOT_KEYWORDS = {
    "load_policy": {"root"},
    "render_all_rulesets": {"root"},
    "apply_rulesets": {"root", "policy_root", "payloads"},
}


def _consumer_boundary_violations(source: str, filename: str = "sample.py") -> list[str]:
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    call_aliases = {name: name for name in _ROOT_KEYWORDS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name in _ROOT_KEYWORDS:
                    call_aliases[imported.asname or imported.name] = imported.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"MODULE_SOURCE_ROOT", "POLICY_DATA_ROOT"}:
            violations.append(f"{filename}:{node.lineno}: installed root {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in {"MODULE_SOURCE_ROOT", "POLICY_DATA_ROOT"}:
            violations.append(f"{filename}:{node.lineno}: installed root attribute {node.attr}")
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            canonical = call_aliases.get(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            canonical = node.func.attr if node.func.attr in _ROOT_KEYWORDS else None
        else:
            canonical = None
        if canonical is None:
            continue
        if not any(keyword.arg in _ROOT_KEYWORDS[canonical] for keyword in node.keywords):
            violations.append(f"{filename}:{node.lineno}: {canonical} without snapshot root")
    return violations


def test_consumer_modules_cannot_read_installed_source_or_policy_roots() -> None:
    violations: list[str] = []
    for relative in CONSUMER_MODULES:
        violations.extend(_consumer_boundary_violations(Path(relative).read_text(encoding="utf-8"), relative))
    assert violations == []


@pytest.mark.parametrize(
    "source",
    [
        "import aviato.policy as p\np.load_policy()\n",
        "from aviato.policy import load_policy as lp\nlp()\n",
        "import aviato.rulesets as r\nr.render_all_rulesets()\n",
        "from aviato.rulesets import apply_rulesets as apply\napply([])\n",
    ],
)
def test_boundary_analysis_detects_qualified_and_aliased_rootless_calls(source: str) -> None:
    assert _consumer_boundary_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "import aviato.policy as p\np.load_policy(root=snapshot)\n",
        "from aviato.policy import load_policy as lp\nlp(root=snapshot)\n",
        "import aviato.rulesets as r\nr.render_all_rulesets(root=snapshot)\n",
        "from aviato.rulesets import apply_rulesets as apply\napply([], payloads=payloads)\n",
    ],
)
def test_boundary_analysis_accepts_qualified_and_aliased_snapshot_calls(source: str) -> None:
    assert _consumer_boundary_violations(source) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["onboard", "{repo}", "--profile", "python-library", "--pin", "1", "--write"],
        ["onboard", "owner/repo", "--profile", "python-library", "--pin", "1", "--open-pr"],
        ["provision", "owner/new", "--profile", "python-library", "--pin", "1"],
        ["repin", "{repo}", "1", "--write"],
        ["repin", "owner/repo", "1", "--open-pr"],
    ],
)
def test_unresolved_pin_escape_hatch_is_rejected_before_any_boundary(
    argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def crossed(*_args: object, **_kwargs: object) -> object:
        pytest.fail("unresolved-pin invocation crossed clone/fetch/render/write boundary")

    for name in (
        "run",
        "_open_consumer_context",
        "_open_new_context",
        "_open_published_snapshot",
        "resolve_profile",
        "materialize_items",
        "_dump_consumer_declaration",
    ):
        monkeypatch.setattr("aviato.cli." + name, crossed)

    rendered = [part.format(repo=tmp_path) for part in argv]
    rc = main([*rendered, "--allow-unresolved-pin"])

    assert rc == 2
    assert "no longer supported" in capsys.readouterr().err


def _snapshot_tree(tmp_path: Path) -> Path:
    root = tmp_path / "fetched-library"
    shutil.copytree(Path("aviato/library"), root)
    profile = yaml.safe_load((root / "python-library.yaml").read_text(encoding="utf-8"))
    profile["name"] = "fetched-python-library"
    (root / "python-library.yaml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("mode", "argv", "consumer"),
    [
        ("resolve", ["onboard", "{repo}", "--profile", "python-library", "--pin", "1"], True),
        ("resolve", ["onboard", "{repo}", "--profile", "python-library", "--pin", "1", "--write"], True),
        ("resolve", ["onboard", "owner/repo", "--profile", "python-library", "--pin", "1", "--open-pr"], False),
        ("resolve", ["doctor", "{repo}", "--no-remote-probe"], True),
        ("materialize", ["sync", "{repo}"], True),
        ("scan", ["scan", "{repo}"], True),
        ("resolve", ["repin", "{repo}", "1"], True),
        ("repin", ["repin", "owner/repo", "1", "--open-pr"], True),
        ("expected", ["offboard", "{repo}"], True),
        ("expected", ["offboard", "owner/repo", "--open-pr"], True),
        ("resolve", ["complete-protection", "{repo}"], True),
        ("resolve", ["provision", "owner/new", "--pin", "1"], False),
        ("resolve", ["drift-report", "{repo}"], True),
        ("resolve", ["bump-version", "1.2.3", "{repo}"], True),
        ("resolve", ["reconcile", "{repo}", "issue"], True),
        ("profile-checks", ["apply-rulesets", "owner/repo", "--declaration", "{decl}"], True),
        ("profile-checks", ["render-rulesets", "--pin", "1", "--profile", "python-library"], False),
        ("audit-policy", ["audit", "--repo", "{repo}"], True),
        ("lint-policy", ["lint-actions", "{repo}"], True),
    ],
)
def test_every_pin_bearing_command_uses_the_fetched_snapshot_not_installed_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    argv: list[str],
    consumer: bool,
) -> None:
    from aviato import cli
    from aviato.plugins import actionpins

    snapshot_root = _snapshot_tree(tmp_path)
    snapshot = SimpleNamespace(registry=Registry(snapshot_root), policy_root=snapshot_root)
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    declaration = repo / ".github/aviato.yaml"
    declaration.parent.mkdir()
    declaration.write_text(
        "profile: python-library\nprofile-identity: aviato-profile/python-library/v1\nversion: '1'\n"
        "variables:\n  distribution-name: acme\n  import-name: acme\n",
        encoding="utf-8",
    )

    opened: list[str] = []

    def open_consumer(_root: Path, _decl: object):
        opened.append("consumer")
        return snapshot

    def open_published(*_args: object):
        opened.append("published")
        return snapshot

    monkeypatch.setattr(cli, "_open_consumer_context", open_consumer)
    monkeypatch.setattr(cli, "_open_published_snapshot", open_published)
    monkeypatch.setattr(cli, "_open_new_context", open_published)
    monkeypatch.setattr(cli, "remote_url", lambda _root: "https://github.com/owner/consumer.git")

    class ContextConsumed(RuntimeError):
        pass

    def consume_registry(registry: object, *_args: object, **_kwargs: object) -> None:
        assert registry is snapshot.registry
        raise ContextConsumed

    def consume_scan(_paths: object, registry: object, **_kwargs: object) -> None:
        consume_registry(registry)

    def consume_profile(registry: object, *_args: object, **_kwargs: object) -> None:
        consume_registry(registry)

    def consume_policy(root: Path) -> None:
        assert root == snapshot.policy_root
        raise ContextConsumed

    def consume_lint(_root: Path, **kwargs: object) -> None:
        assert kwargs["policy_root"] == snapshot.policy_root
        raise ContextConsumed

    def fake_run(command: list[str], **_kwargs: object):
        if command[:3] == ["gh", "repo", "clone"]:
            clone = Path(command[-1])
            clone.mkdir(parents=True)
            subprocess.run(["git", "-C", str(clone), "init"], check=True, capture_output=True)
            if "offboard" in argv or "repin" in argv:
                clone_decl = clone / ".github/aviato.yaml"
                clone_decl.parent.mkdir()
                clone_decl.write_text(declaration.read_text(encoding="utf-8"), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    if mode == "resolve":
        monkeypatch.setattr(cli, "resolve_profile", consume_registry)
    elif mode == "materialize":
        monkeypatch.setattr(cli, "materialize_items", consume_registry)
    elif mode == "scan":
        monkeypatch.setattr(cli, "scan_fleet", consume_scan)
    elif mode == "repin":
        monkeypatch.setattr(cli, "plan_repin", consume_registry)
    elif mode == "expected":
        monkeypatch.setattr(cli, "_expected_artifacts", consume_registry)
    elif mode == "profile-checks":
        monkeypatch.setattr(cli, "_profile_status_checks", consume_profile)
    elif mode == "audit-policy":
        monkeypatch.setattr(cli, "load_policy", consume_policy)
    elif mode == "lint-policy":
        monkeypatch.setattr(actionpins, "action_pin_violations", consume_lint)

    expanded = [part.format(repo=repo, decl=declaration) for part in argv]
    with pytest.raises(ContextConsumed):
        main(expanded)
    assert ("consumer" in opened) is consumer


def test_fetched_snapshot_bytes_drive_onboard_and_ruleset_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aviato import cli

    snapshot_root = _snapshot_tree(tmp_path)
    workflows = yaml.safe_load((snapshot_root / "bundles/workflows/python-library-wf.yaml").read_text(encoding="utf-8"))
    workflows["add"].append("fetched-only-pipeline")
    (snapshot_root / "bundles/workflows/python-library-wf.yaml").write_text(
        yaml.safe_dump(workflows, sort_keys=False), encoding="utf-8"
    )
    pipelines = yaml.safe_load((snapshot_root / "pipelines.yaml").read_text(encoding="utf-8"))
    pipelines["fetched-only-pipeline"] = {
        "identity": "pipeline/fetched-only/v2",
        "envelope": "ci",
        "privileges": [],
        "runner": "ubuntu-latest",
        "jobs": {
            "fetched-only": {
                "identity": "job/fetched-only/v2",
                "fragment": "workflow-fragments/fetched-only.yml",
                "permissions": [],
                "runner": "ubuntu-latest",
            }
        },
    }
    (snapshot_root / "pipelines.yaml").write_text(yaml.safe_dump(pipelines, sort_keys=False), encoding="utf-8")
    (snapshot_root / "workflow-fragments/fetched-only.yml").write_text(
        'runs-on: ubuntu-latest\npermissions: {}\nsteps:\n  - run: "true"\n',
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(registry=Registry(snapshot_root), policy_root=snapshot_root)
    monkeypatch.setattr(cli, "_open_published_snapshot", lambda _pin: snapshot)

    assert main(["onboard", "owner/repo", "--profile", "python-library", "--pin", "1"]) == 0
    assert "fetched-only-pipeline" in capsys.readouterr().out

    manifest = yaml.safe_load((snapshot_root / "rulesets.yml").read_text(encoding="utf-8"))
    payload_path = snapshot_root / manifest["rulesets"][0]["file"]
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["name"] = "fetched-snapshot-ruleset"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["render-rulesets", "--pin", "1"]) == 0
    assert "fetched-snapshot-ruleset" in capsys.readouterr().out


def test_unresolved_pin_escape_hatch_is_rejected_before_render_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from aviato import cli

    monkeypatch.setattr(cli, "_open_new_context", lambda *_args, **_kwargs: pytest.fail("render authority opened"))
    rc = main(
        [
            "onboard",
            str(tmp_path),
            "--profile",
            "python-library",
            "--pin",
            "1",
            "--write",
            "--allow-unresolved-pin",
        ]
    )
    assert rc == 2
    assert "verified, commit-addressed Library bytes are mandatory" in capsys.readouterr().err
    assert not (tmp_path / ".github").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["onboard", "owner/repo", "--profile", "python-library"],
        ["apply-rulesets", "owner/repo"],
        ["render-rulesets"],
    ],
)
def test_unpinned_consumer_modes_require_a_pin_or_declaration_context(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "pin" in capsys.readouterr().err.lower()


def test_ruleset_audit_and_lint_consumers_use_snapshot_policy_not_installed_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aviato import audit
    from aviato.plugins.actionpins import action_pin_violations
    from aviato.rulesets import render_all_rulesets

    snapshot_root = _snapshot_tree(tmp_path)
    policy = yaml.safe_load((snapshot_root / "policy.yml").read_text(encoding="utf-8"))
    policy["library"]["repository"] = "example/fetched-library"
    policy["release"]["tag_pattern"] = "^fetched-[0-9]+$"
    (snapshot_root / "policy.yml").write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    payloads = render_all_rulesets(root=snapshot_root)
    assert payloads

    repo = tmp_path / "consumer"
    (repo / "aviato/library/workflow-fragments").mkdir(parents=True)
    (repo / "aviato/library/workflow-fragments/example.yml").write_text(
        "jobs:\n  call:\n    uses: example/fetched-library/.github/workflows/reusable.yml@1\n",
        encoding="utf-8",
    )
    assert (
        action_pin_violations(
            repo,
            policy_root=snapshot_root,
            library_repository="example/fetched-library",
        )
        == []
    )

    monkeypatch.setattr(audit, "tags", lambda _repo: ["fetched-7", "1.2.3"])
    monkeypatch.setattr(audit, "remote_url", lambda _repo: "")
    row = audit.audit_repo(repo, root=repo, policy=policy)
    assert row.invalid_tags == "1.2.3"
