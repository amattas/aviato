from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pytest

from aviato import github
from aviato.command import CommandError
from aviato.core.ports import RepositoryIdentity
from aviato.rulesets import render_all_rulesets

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


class _NamedFile(Protocol):
    name: str


def _record_named_files[**P, TNamedFile: _NamedFile](
    fn: Callable[P, TNamedFile], created: list[Path]
) -> Callable[P, TNamedFile]:
    def recording(*args: P.args, **kwargs: P.kwargs) -> TNamedFile:
        handle = fn(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    return recording


def _tag_ruleset_payload() -> JsonObject:
    return cast(
        JsonObject,
        next(
            payload
            for payload in render_all_rulesets(root=Path("aviato/library"))
            if payload["target"] == "tag"
        ),
    )


def _capture_payload(cmd: list[str]) -> JsonObject:
    return cast(JsonObject, json.loads(Path(cmd[cmd.index("--input") + 1]).read_text(encoding="utf-8")))


def test_gh_json_raises_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "authentication failed")

    monkeypatch.setattr(github, "run", fake_run)

    with pytest.raises(github.GitHubAPIError):
        github.gh_json("repos/amattas/aviato")


def test_gh_json_can_allow_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "not found")

    monkeypatch.setattr(github, "run", fake_run)

    assert github.gh_json("repos/amattas/aviato/rulesets", default=[], allow_error=True) == []


@pytest.mark.parametrize(
    "ref_result",
    [
        subprocess.CompletedProcess(["gh"], 1, "", "gh: Bad credentials (HTTP 401)"),
        subprocess.CompletedProcess(["gh"], 1, "", "gh: API rate limit exceeded (HTTP 429)"),
        subprocess.CompletedProcess(["gh"], 1, "", "request timed out"),
        subprocess.CompletedProcess(["gh"], 1, "", "gh: Service unavailable (HTTP 503)"),
        subprocess.CompletedProcess(["gh"], 0, "not-json", ""),
        subprocess.CompletedProcess(["gh"], 0, '{"object":{"type":"commit","sha":"short"}}', ""),
    ],
    ids=("auth", "rate-limit", "timeout", "server", "invalid-json", "malformed-object"),
)
def test_auth_rate_limit_timeout_server_and_malformed_reads_are_errors(
    monkeypatch: pytest.MonkeyPatch,
    ref_result: subprocess.CompletedProcess[str],
) -> None:
    repository_endpoint = "repos/o/r"
    ref_endpoint = f"{repository_endpoint}/git/ref/tags/v1"
    repository_payload = {"id": 17, "node_id": "R_test", "full_name": "o/r", "default_branch": "main"}

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        endpoint = command[2]
        if endpoint == repository_endpoint:
            return subprocess.CompletedProcess(command, 0, json.dumps(repository_payload), "")
        if endpoint == ref_endpoint:
            return subprocess.CompletedProcess(command, ref_result.returncode, ref_result.stdout, ref_result.stderr)
        raise AssertionError(f"unexpected GitHub API read: {endpoint}")

    monkeypatch.setattr(github, "run", fake_run)
    monkeypatch.setattr(github.time, "sleep", lambda _: None)

    identity = github.repository_identity("o/r")
    outcome = github.read_git_ref(identity, github.GitRefNamespace.TAGS, "v1")

    assert outcome.status.value == "error"
    assert outcome.error


def test_git_object_launch_failure_is_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")

    def unavailable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise CommandError(["gh", "api", "repos/o/r/git/ref/tags/v1"], 127, "could not execute 'gh'")

    monkeypatch.setattr(github, "run", unavailable)

    outcome = github.read_git_ref(identity, github.GitRefNamespace.TAGS, "v1")

    assert outcome.status.value == "error"
    assert outcome.error and "could not execute" in outcome.error


def test_repository_identity_launch_failure_is_a_github_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise CommandError(["gh", "api", "repos/o/r"], 127, "could not execute 'gh'")

    monkeypatch.setattr(github, "run", unavailable)

    with pytest.raises(github.GitHubAPIError, match="could not execute"):
        github.repository_identity("o/r")


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "owner",
        "owner/repo/extra",
        "owner//repo",
        ".owner/repo",
        "-owner/repo",
        "_owner/repo",
        "owner/.",
        "owner/..",
        "owner/../repo",
        "owner/repo?query",
        "owner/repo#fragment",
    ],
)
def test_invalid_repository_slug_is_rejected_before_api_call(
    monkeypatch: pytest.MonkeyPatch,
    slug: str,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github,
        "run",
        lambda command, **_kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0, "{}", ""),
    )

    with pytest.raises(ValueError, match="OWNER/REPO"):
        github.repository_identity(slug)

    assert calls == []


def test_dot_leading_repository_segment_preserves_correlated_api_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = "github/.github"
    repository_endpoint = f"repos/{slug}"
    ref_endpoint = f"{repository_endpoint}/git/ref/heads/main"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[2] == repository_endpoint:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "id": 17,
                        "node_id": "R_dot",
                        "full_name": slug,
                        "default_branch": "main",
                    }
                ),
                "",
            )
        if command[2] == ref_endpoint:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"object": {"type": "commit", "sha": "a" * 40}}),
                "",
            )
        raise AssertionError(f"unexpected GitHub API read: {command[2]}")

    monkeypatch.setattr(github, "run", fake_run)

    identity = github.repository_identity(slug)
    outcome = github.read_git_ref(identity, github.GitRefNamespace.HEADS, identity.default_branch)

    assert identity.full_name == slug
    assert outcome.endpoint == ref_endpoint
    assert calls == [["gh", "api", repository_endpoint], ["gh", "api", ref_endpoint]]


@pytest.mark.parametrize(
    "ref_name",
    [
        "",
        ".",
        "foo//bar",
        "foo/./bar",
        "foo..bar",
        "bad?query",
        "bad\x01control",
        r"bad\ref",
        "release.lock",
        "foo@{bar",
        "bad~ref",
        "bad^ref",
        "bad:ref",
        "bad*ref",
        "bad[ref",
    ],
)
def test_invalid_git_ref_name_is_rejected_before_api_call(
    monkeypatch: pytest.MonkeyPatch,
    ref_name: str,
) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github,
        "run",
        lambda command, **_kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0, "{}", ""),
    )

    with pytest.raises(ValueError, match="Git ref"):
        github.read_git_ref(identity, github.GitRefNamespace.HEADS, ref_name)

    assert calls == []


@pytest.mark.parametrize("namespace", [github.GitRefNamespace.HEADS, github.GitRefNamespace.TAGS])
@pytest.mark.parametrize(("ref_name", "encoded_name"), [("@", "%40"), ("-leading", "-leading")])
def test_fully_qualified_api_refs_preserve_valid_at_and_leading_hyphen_names(
    monkeypatch: pytest.MonkeyPatch,
    namespace: github.GitRefNamespace,
    ref_name: str,
    encoded_name: str,
) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")
    endpoint = f"repos/o/r/git/ref/{namespace.value}/{encoded_name}"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"object": {"type": "commit", "sha": "a" * 40}}),
            "",
        )

    monkeypatch.setattr(github, "run", fake_run)

    outcome = github.read_git_ref(identity, namespace, ref_name)

    assert outcome.status.value == "found"
    assert outcome.endpoint == endpoint
    assert calls == [["gh", "api", endpoint]]


def test_valid_nested_ref_uses_typed_namespace_and_encoded_correlated_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")
    endpoint = "repos/o/r/git/ref/heads/release%2F2026%2F%23v1"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"object": {"type": "commit", "sha": "a" * 40}}),
            "",
        )

    monkeypatch.setattr(github, "run", fake_run)

    outcome = github.read_git_ref(identity, github.GitRefNamespace.HEADS, "release/2026/#v1")

    assert outcome.status.value == "found"
    assert calls == [["gh", "api", endpoint]]


def test_annotated_tag_reader_rejects_non_sha_before_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        github,
        "run",
        lambda command, **_kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0, "{}", ""),
    )

    with pytest.raises(ValueError, match="SHA"):
        github.read_annotated_tag(identity, "not-a-sha")

    assert calls == []


def test_codeql_merge_protection_requires_exact_active_branch_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "default_branch", lambda slug: "main")
    effective: list[JsonObject] = [
        {"type": "pull_request", "ruleset_source_type": "Repository"},
        {
            "type": "code_scanning",
            "parameters": {"code_scanning_tools": [dict(github.EXPECTED_CODEQL_RULE)]},
        },
    ]
    monkeypatch.setattr(github, "gh_json_paginated", lambda endpoint, default=None: effective)
    assert github.codeql_merge_protection_present("o/r") is True

    effective[1] = {
        "type": "code_scanning",
        "parameters": {
            "code_scanning_tools": [
                {**cast(JsonObject, github.EXPECTED_CODEQL_RULE), "security_alerts_threshold": "critical"}
            ]
        },
    }
    assert github.codeql_merge_protection_present("o/r") is False

    effective.pop()
    assert github.codeql_merge_protection_present("o/r") is False


def test_codeql_merge_protection_reads_effective_nested_default_branch_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "default_branch", lambda slug: "release/main")
    endpoints: list[str] = []

    def effective(endpoint: str, default: object = None) -> list[JsonObject]:
        endpoints.append(endpoint)
        return [
            {
                "type": "code_scanning",
                "parameters": {"code_scanning_tools": [dict(github.EXPECTED_CODEQL_RULE)]},
            }
        ]

    monkeypatch.setattr(github, "gh_json_paginated", effective)
    assert github.codeql_merge_protection_present("o/r") is True
    assert endpoints == ["repos/o/r/rules/branches/release%2Fmain"]


@pytest.mark.parametrize(
    "bad_value",
    [
        {},
        [7],
        [{"type": 7}],
        [{"type": "code_scanning"}],
        [{"type": "code_scanning", "parameters": []}],
        [{"type": "code_scanning", "parameters": {"code_scanning_tools": {}}}],
        [{"type": "code_scanning", "parameters": {"code_scanning_tools": [7]}}],
        [{"type": "code_scanning", "parameters": {"code_scanning_tools": [{"tool": "CodeQL"}]}}],
    ],
)
def test_codeql_merge_protection_fails_closed_on_successful_malformed_shapes(
    monkeypatch: pytest.MonkeyPatch, bad_value: object
) -> None:
    monkeypatch.setattr(github, "default_branch", lambda slug: "main")
    monkeypatch.setattr(github, "gh_json_paginated", lambda endpoint, default=None: bad_value)
    with pytest.raises(github.GitHubAPIError):
        github.codeql_merge_protection_present("o/r")


def test_gh_json_optional_raises_on_non_404_containing_not_found_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 403/auth/5xx whose stderr merely CONTAINS "not found"/"no such" must RAISE, not be
    # read as an empty 404 — keying off the bare phrase re-opens the §2.7 fail-OPEN read
    # (a falsely-"unprotected"/"no-issue" state). Only the HTTP 404 status is a genuine 404.
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "gh: Resource not found or no such host (HTTP 403)")

    monkeypatch.setattr(github, "run", fake_run)
    with pytest.raises(github.GitHubAPIError):
        github.gh_json_optional("repos/o/r/branches/main/protection", default={})


def test_gh_json_optional_returns_default_on_genuine_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(github, "run", fake_run)
    assert github.gh_json_optional("repos/o/r/branches/main/protection", default={}) == {}


@pytest.mark.parametrize("terminal_status", [403, 500])
def test_gh_json_optional_rejects_embedded_404_before_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: int,
) -> None:
    stderr = f"gh: upstream Not Found (HTTP 404)\ngh: request failed (HTTP {terminal_status})"
    monkeypatch.setattr(
        github,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["gh"], 1, "", stderr),
    )

    with pytest.raises(github.GitHubAPIError):
        github.gh_json_optional("repos/o/r/branches/main/protection", default={})


def test_paginated_optional_rejects_embedded_404_before_terminal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = "gh: upstream Not Found (HTTP 404)\ngh: forbidden (HTTP 403)"
    monkeypatch.setattr(
        github,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["gh"], 1, "", stderr),
    )

    with pytest.raises(github.GitHubAPIError):
        github.gh_json_paginated_optional("repos/o/r/rulesets", default=[])


@pytest.mark.parametrize(
    ("stderr", "expected_status"),
    [
        ("gh: Not Found (HTTP 404)", "not_found"),
        ("gh: upstream Not Found (HTTP 404)\ngh: forbidden (HTTP 403)", "error"),
        ("gh: upstream Not Found (HTTP 404)\ngh: unavailable (HTTP 500)", "error"),
    ],
    ids=("terminal-404", "terminal-403", "terminal-500"),
)
def test_terminal_http_status_controls_not_found_classification(
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    expected_status: str,
) -> None:
    identity = RepositoryIdentity(database_id=17, node_id="R_test", full_name="o/r", default_branch="main")
    monkeypatch.setattr(
        github,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", stderr),
    )

    outcome = github.read_git_ref(identity, github.GitRefNamespace.TAGS, "v1")

    assert outcome.status.value == expected_status
    assert bool(outcome.error) is (expected_status == "error")


def test_upsert_ruleset_posts_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    calls: list[list[str]] = []

    def recording_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", recording_run)
    result = github.upsert_ruleset("o/r", {"name": "Common: protect default branch"}, apply=True)
    assert "Created" in result.message
    method = calls[0][calls[0].index("--method") + 1]
    assert method == "POST"
    assert "repos/o/r/rulesets" in calls[0]


def test_upsert_ruleset_puts_to_existing_id_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github,
        "repository_rulesets",
        lambda slug: [{"name": "Common: protect default branch", "id": 4242}],
    )
    calls: list[list[str]] = []

    def recording_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", recording_run)
    result = github.upsert_ruleset("o/r", {"name": "Common: protect default branch"}, apply=True)
    assert "Updated" in result.message
    method = calls[0][calls[0].index("--method") + 1]
    assert method == "PUT"
    assert "repos/o/r/rulesets/4242" in calls[0]


def test_apply_planned_ruleset_uses_exact_selected_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        github,
        "_submit_ruleset",
        lambda endpoint, method, payload: submitted.append((endpoint, method)),
    )

    github.apply_planned_ruleset("o/r", {"name": "Protect"}, ruleset_id=41)
    github.apply_planned_ruleset("o/r", {"name": "Create"}, ruleset_id=None)

    assert submitted == [("repos/o/r/rulesets/41", "PUT"), ("repos/o/r/rulesets", "POST")]


def test_upsert_ruleset_matches_by_name_and_target_not_name_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    # N1 (cycle 11): a live ruleset that shares a NAME but targets a different ref kind must NOT be
    # updated — that would overwrite the wrong protected resource. The desired payload creates its own.
    calls: list[list[str]] = []

    def recording_run(cmd: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(github, "run", recording_run)
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [{"name": "Protect", "target": "tag", "id": 99}])
    result = github.upsert_ruleset("o/r", {"name": "Protect", "target": "branch"}, apply=True)
    assert "Created" in result.message
    assert calls[0][calls[0].index("--method") + 1] == "POST"
    # Same (name, target) → update the matching one.
    calls.clear()
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [{"name": "Protect", "target": "branch", "id": 7}])
    result2 = github.upsert_ruleset("o/r", {"name": "Protect", "target": "branch"}, apply=True)
    assert "Updated" in result2.message and "repos/o/r/rulesets/7" in calls[0]


def test_upsert_ruleset_dry_run_does_not_mutate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    monkeypatch.setattr(
        github, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call gh on dry run"))
    )
    msg = github.upsert_ruleset("o/r", {"name": "X"}, apply=False)
    assert msg.message.startswith("DRY RUN")


def test_upsert_ruleset_requires_name(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        github.upsert_ruleset("o/r", {}, apply=True)


@pytest.mark.parametrize("existing", [[], [{"name": "Common: release tag format", "target": "tag", "id": 42}]])
def test_upsert_ruleset_retries_precise_unsupported_tag_metadata_422_once(
    monkeypatch: pytest.MonkeyPatch, existing: list[JsonObject]
) -> None:
    payload = _tag_ruleset_payload()
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: existing)
    calls: list[list[str]] = []
    submitted: list[JsonObject] = []
    payload_paths: list[Path] = []
    payload_modes: list[int] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        submitted.append(_capture_payload(cmd))
        path = Path(cmd[cmd.index("--input") + 1])
        payload_paths.append(path)
        payload_modes.append(path.stat().st_mode & 0o777)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                "gh: Validation Failed: tag_name_pattern is not a supported repository rule type (HTTP 422)",
            )
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(github, "run", fake_run)
    result = github.upsert_ruleset("o/r", payload, apply=True)

    assert result.degraded_rules == ("tag_name_pattern",)
    assert len(calls) == 2
    assert [cmd[cmd.index("--method") + 1] for cmd in calls] == (["PUT", "PUT"] if existing else ["POST", "POST"])
    assert submitted[0] == payload
    rules = cast(list[JsonObject], payload["rules"])
    assert submitted[1] == {**payload, "rules": [rule for rule in rules if rule["type"] != "tag_name_pattern"]}
    assert payload_modes == [0o600, 0o600]
    assert not any(path.exists() for path in payload_paths)


@pytest.mark.parametrize(
    "structured",
    (
        '{"message":"Validation Failed","errors":['
        '{"field":"rules/2/type","value":"tag_name_pattern","code":"invalid"}]}',
        '{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': "]}',
    ),
    ids=("object-entry", "live-string-entry"),
)
def test_upsert_ruleset_reads_structured_unsupported_tag_error_from_stdout(
    monkeypatch: pytest.MonkeyPatch,
    structured: str,
) -> None:
    payload = _tag_ruleset_payload()
    monkeypatch.setattr(
        github,
        "repository_rulesets",
        lambda slug: [{"name": "Common: release tag format", "target": "tag", "id": 42}],
    )
    calls: list[list[str]] = []
    submitted: list[JsonObject] = []
    payload_paths: list[Path] = []
    payload_modes: list[int] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        submitted.append(_capture_payload(cmd))
        path = Path(cmd[cmd.index("--input") + 1])
        payload_paths.append(path)
        payload_modes.append(path.stat().st_mode & 0o777)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, structured, "gh: Validation Failed (HTTP 422)")
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    monkeypatch.setattr(github, "run", fake_run)

    result = github.upsert_ruleset("o/r", payload, apply=True)

    assert result.degraded_rules == ("tag_name_pattern",)
    assert len(calls) == 2
    assert submitted[0] == payload
    rules = cast(list[JsonObject], payload["rules"])
    assert submitted[1] == {**payload, "rules": [rule for rule in rules if rule["type"] != "tag_name_pattern"]}
    assert payload_modes == [0o600, 0o600]
    assert not any(path.exists() for path in payload_paths)


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Validation Failed: bad conditions (HTTP 422)",
        "gh: tag_name_pattern validation failed for another reason (HTTP 422)",
        "gh: forbidden (HTTP 403)",
        "gh: server unavailable (HTTP 500)",
        "connection reset by peer",
        "gh: malformed response",
    ],
)
def test_upsert_ruleset_does_not_retry_other_failures(monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", stderr)

    monkeypatch.setattr(github, "run", fake_run)
    with pytest.raises(github.GitHubAPIError) as exc:
        github.upsert_ruleset("o/r", _tag_ruleset_payload(), apply=True)
    assert exc.value.stderr == stderr
    assert len(calls) == 1


@pytest.mark.parametrize(
    "stderr",
    [
        'For rules/2/type, "tag_name_pattern" is not a valid value. (HTTP 422)',
        "Rule type tag_name_pattern is an unsupported repository rule type. (HTTP 422)",
        '{"message":"Validation Failed","errors":['
        '{"field":"rules/2/type","value":"tag_name_pattern","code":"invalid"}]} (HTTP 422)',
    ],
)
def test_unsupported_tag_metadata_classifier_accepts_correlated_rule_type_rejections(stderr: str) -> None:
    assert github._unsupported_tag_metadata_rule(stderr) is True


@pytest.mark.parametrize(
    "stderr",
    [
        "tag_name_pattern failed validation\nunsupported repository rule type (HTTP 422)",
        '{"message":"Validation Failed","errors":['
        '{"field":"rules/2/parameters/pattern","value":"tag_name_pattern","code":"invalid"},'
        '{"field":"rules/4/type","value":"deletion","code":"unsupported"}]} (HTTP 422)',
        'For rules/2/parameters/pattern, "tag_name_pattern" is not a valid value. (HTTP 422)',
        'For conditions/ref_name, "tag_name_pattern" is unsupported. (HTTP 422)',
        "tag_name_pattern is valid, but deletion is an unsupported repository rule type (HTTP 422)",
        'gh: Validation Failed (HTTP 422)\n{"message":"Validation Failed","errors":["Invalid rule \'deletion\': "]}',
        "gh: Validation Failed (HTTP 422)\n"
        '{"message":"Validation Failed","errors":["Invalid field \'tag_name_pattern\': "]}',
        "gh: Validation Failed (HTTP 422)\n"
        '{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': malformed regex"]}',
        "gh: Validation Failed (HTTP 422)\n"
        '{"message":"Validation Failed","errors":["Invalid rule", "\'tag_name_pattern\': "]}',
        '{"message":"Validation Failed","errors":["Invalid rule \'tag_name_pattern\': "]}',
    ],
)
def test_unsupported_tag_metadata_classifier_rejects_uncorrelated_or_non_type_errors(stderr: str) -> None:
    assert github._unsupported_tag_metadata_rule(stderr) is False


def test_upsert_ruleset_removes_temp_file_when_json_serialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    created: list[Path] = []
    tempfile_module = tempfile
    monkeypatch.setattr(
        tempfile_module,
        "NamedTemporaryFile",
        _record_named_files(tempfile_module.NamedTemporaryFile, created),
    )
    monkeypatch.setattr(
        github,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("gh must not run after serialization failure")),
    )
    payload = _tag_ruleset_payload()
    cast(dict[str, object], payload)["not_json"] = {"a-set"}

    with pytest.raises(TypeError, match="JSON serializable"):
        github.upsert_ruleset("o/r", payload, apply=True)

    assert len(created) == 1
    assert not created[0].exists()


def test_upsert_ruleset_propagates_degraded_retry_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    errors = iter(
        [
            "tag_name_pattern is not a supported repository rule type (HTTP 422)",
            "service unavailable (HTTP 503)",
        ]
    )
    monkeypatch.setattr(
        github,
        "run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 1, "", next(errors)),
    )
    with pytest.raises(github.GitHubAPIError, match="503"):
        github.upsert_ruleset("o/r", _tag_ruleset_payload(), apply=True)


def test_upsert_ruleset_dry_run_promises_full_payload_not_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [])
    result = github.upsert_ruleset("o/r", _tag_ruleset_payload(), apply=False)
    assert result.degraded_rules == ()
    assert "full ruleset" in result.message.lower()


def test_repository_rulesets_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    # A repo with more rulesets than one page must not hide an existing ruleset on a
    # later page — otherwise upsert would POST a duplicate instead of PUT-updating.
    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert "--paginate" in cmd and "--slurp" in cmd, "rulesets list must be paginated"
        body = '[[{"name": "other", "id": 1}], [{"name": "Common: protect default branch", "id": 99}]]'
        return subprocess.CompletedProcess(cmd, 0, body, "")

    monkeypatch.setattr(github, "run", fake_run)
    names = [r["name"] for r in github.repository_rulesets("o/r")]
    assert "Common: protect default branch" in names


def test_settings_read_token_scope_overrides_then_restores_gh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    # §5.6/§11.2: inside the scope gh reads use the admin READ token; afterwards GH_TOKEN is
    # restored so the issue WRITES run under the ambient platform token (the admin token mutates
    # nothing — it is read-only in use).
    monkeypatch.setenv("GH_TOKEN", "platform-token")
    monkeypatch.setenv(github.SETTINGS_READ_TOKEN_ENV, "admin-read-token")
    with github.settings_read_token_scope():
        assert os.environ["GH_TOKEN"] == "admin-read-token"
    assert os.environ["GH_TOKEN"] == "platform-token"


def test_settings_read_token_scope_is_noop_without_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setenv("GH_TOKEN", "platform-token")
    monkeypatch.delenv(github.SETTINGS_READ_TOKEN_ENV, raising=False)
    with github.settings_read_token_scope():
        assert os.environ["GH_TOKEN"] == "platform-token"  # unchanged
    assert os.environ["GH_TOKEN"] == "platform-token"


def test_pages_build_type_workflow_returns_none_on_404_or_missing_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    # R7-3-PAGES-§5.14: a 404 from /pages conflates "off" with "no perms" and "invisible" — the
    # honest mapping is unknown (None), per §5.14 "absence/unreadable reads as broken, not clean".
    # R7-3-PAGES-SCHEMA: a present dict lacking build_type (schema drift) is also unknown, not no.
    from aviato import github as gh

    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: None)  # the 404 path
    assert gh.pages_build_type_is_workflow("o/r") is None
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: "weird-non-dict")
    assert gh.pages_build_type_is_workflow("o/r") is None
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"public": True})  # no build_type
    assert gh.pages_build_type_is_workflow("o/r") is None


def test_pages_build_type_workflow_resolves_workflow_vs_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The two determinate cases the API DOES distinguish: Actions-sourced (workflow) vs branch.
    from aviato import github as gh

    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"build_type": "workflow"})
    assert gh.pages_build_type_is_workflow("o/r") is True
    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"build_type": "legacy"})
    assert gh.pages_build_type_is_workflow("o/r") is False


@pytest.mark.parametrize("build_type", [True, 1, [], {}, "actions", "branch", "WORKFLOW", ""])
def test_pages_build_type_workflow_returns_none_for_malformed_or_unknown_enum(
    monkeypatch: pytest.MonkeyPatch, build_type: object
) -> None:
    from aviato import github as gh

    monkeypatch.setattr(gh, "gh_json_optional", lambda *a, **k: {"build_type": build_type})
    assert gh.pages_build_type_is_workflow("o/r") is None


def test_upsert_ruleset_matches_when_list_omits_target(monkeypatch: pytest.MonkeyPatch) -> None:
    # C12-2: GitHub's ruleset LIST summary may omit `target`. A same-name candidate with no target can
    # only be THIS ruleset, so upsert must UPDATE it (not POST a duplicate / 422).
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [{"id": 7, "name": "protect"}])
    msg = github.upsert_ruleset("o/r", {"name": "protect", "target": "branch"}, apply=False)
    assert "would update" in msg.message and "7" in msg.message
    # A same-name ruleset on a DIFFERENT, explicit target must NOT match (would create the missing one).
    monkeypatch.setattr(github, "repository_rulesets", lambda slug: [{"id": 9, "name": "protect", "target": "tag"}])
    assert "would create" in github.upsert_ruleset("o/r", {"name": "protect", "target": "branch"}, apply=False).message
