from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Never, cast

import pytest

from aviato import cli
from aviato.core.ports import RulesetApplyResult
from aviato.github import GitHubAPIError
from aviato.paths import POLICY_DATA_ROOT

pytestmark = pytest.mark.usefixtures("task3_pinned_context")


def _patch_apply(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Capture every apply_rulesets call instead of touching GitHub."""
    calls: list[dict[str, object]] = []

    def fake(
        slugs: Sequence[str],
        *,
        root: Path,
        apply: bool,
        required_approvals: int | None = None,
        extra_status_checks: Sequence[str] | None = None,
    ) -> list[str]:
        calls.append(
            {"slugs": list(slugs), "apply": apply, "approvals": required_approvals, "checks": extra_status_checks}
        )
        return [f"would upsert on {slug}" for slug in slugs]

    monkeypatch.setattr(cli, "apply_rulesets", fake)
    return calls


def test_apply_rulesets_aggregates_slugs_from_all_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _patch_apply(monkeypatch)
    repos_file = tmp_path / "repos.txt"
    repos_file.write_text("o/three\n# comment\n\no/four\n")
    rc = cli.main(
        ["apply-rulesets", "o/one", "--repo", "o/two", "--repos-file", str(repos_file), "--pin", "0"]
    )
    assert rc == 0
    assert calls[0]["slugs"] == ["o/one", "o/two", "o/three", "o/four"]
    assert calls[0]["apply"] is False  # default is dry-run


def test_apply_rulesets_declaration_preserves_zero_approval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_apply(monkeypatch)
    declaration = Path(__file__).resolve().parents[1] / ".github" / "aviato.yaml"

    rc = cli.main(["apply-rulesets", "amattas/aviato", "--declaration", str(declaration)])

    assert rc == 0
    assert calls == [
        {
            "slugs": ["amattas/aviato"],
            "apply": False,
            "approvals": 0,
            "checks": [
                "ci / Python CI",
                "common-lint / Common lint",
                "security / Security baseline heartbeat",
            ],
        }
    ]


def test_apply_rulesets_requires_a_slug(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["apply-rulesets"])
    assert rc == 2
    assert "at least one repository slug is required" in capsys.readouterr().err


def test_apply_rulesets_warns_on_direct_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _patch_apply(monkeypatch)
    rc = cli.main(["apply-rulesets", "o/r", "--apply", "--pin", "0"])
    assert rc == 0
    assert calls[0]["apply"] is True
    err = capsys.readouterr().err
    assert "WARNING" in err and "reconcile" in err  # §5.7 nudge toward the gated flow


def test_apply_rulesets_maps_github_error_to_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: object, **k: object) -> Never:
        raise GitHubAPIError("repos/o/r/rulesets", 1, "nope")

    monkeypatch.setattr(cli, "apply_rulesets", boom)
    rc = cli.main(["apply-rulesets", "o/r", "--apply", "--pin", "0"])
    assert rc == 1
    assert "GitHub API error" in capsys.readouterr().err


def test_apply_rulesets_unknown_profile_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A bad --profile fails composition (AviatoError) and must be a clean exit-2 operator
    # error, not an uncaught traceback — and must NOT reach apply_rulesets.
    def must_not_run(*a: object, **k: object) -> Never:
        raise AssertionError("apply_rulesets must not be called when the profile is invalid")

    monkeypatch.setattr(cli, "apply_rulesets", must_not_run)
    rc = cli.main(["apply-rulesets", "o/r", "--profile", "no-such-profile", "--apply", "--pin", "0"])
    assert rc == 2


def test_negative_required_approvals_is_rejected_at_parse_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # review #11: a negative --required-approvals would render an invalid ruleset payload
    # (required_approving_review_count: -5) that GitHub rejects only at apply time. argparse must
    # reject it up front (SystemExit(2)), never reaching render/apply.
    for cmd in (
        ["render-rulesets", "--required-approvals", "-5"],
        ["apply-rulesets", "o/r", "--required-approvals", "-1", "--apply"],
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(cmd)
        assert exc.value.code == 2
    # 0 (the documented solo-repo override) is still accepted by the type.
    assert cli._non_negative_int("0") == 0


def test_apply_rulesets_rejects_malformed_slug(capsys: pytest.CaptureFixture[str]) -> None:
    # R3-5: a non-OWNER/REPO slug must fail loud locally (exit 2), not as an API 404.
    assert cli.main(["apply-rulesets", "justaword", "--apply"]) == 2
    assert "OWNER/REPO" in capsys.readouterr().err


@pytest.mark.parametrize(
    "slug",
    ["a/b/c", "a/b?x", "a/b#x", " a/b", "a/b ", "-a/b", "a/-b", "a\\b", "a/b\n", "a/", "/b"],
)
def test_apply_rulesets_rejects_unsafe_slug_before_api(slug: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "apply_rulesets",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API helper must not run")),
    )

    argv = ["apply-rulesets", "--apply"]
    if slug.startswith("-"):
        argv.append("--")
    assert cli.main([*argv, slug]) == 2


def test_apply_rulesets_missing_repos_file_is_clean_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # R3-13: a missing --repos-file is a clean operator error (exit 2 via main()), not a traceback.
    rc = cli.main(["apply-rulesets", "--repos-file", str(tmp_path / "nope.txt"), "--apply"])
    assert rc == 2
    assert "repos-file" in capsys.readouterr().err


def test_parse_var_flags_rejects_empty_key_and_duplicates() -> None:
    # R3-6: empty key and duplicate key are input footguns → fail loud, not silent.
    import pytest as _pytest

    from aviato.cli import _parse_var_flags
    from aviato.core.errors import AviatoError

    assert _parse_var_flags(["k=v"]) == {"k": "v"}
    with _pytest.raises(AviatoError):
        _parse_var_flags(["=v"])
    with _pytest.raises(AviatoError):
        _parse_var_flags(["k=1", "k=2"])


def test_apply_rulesets_streams_messages_before_a_later_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # R2-4-6: apply_rulesets is a generator — a confirmation for each successful upsert is yielded
    # BEFORE a later upsert fails, so the operator sees what was already mutated on the platform.
    from aviato import github, rulesets

    monkeypatch.setattr(rulesets, "render_all_rulesets", lambda **__: [{"name": "r"}])
    seen: list[str] = []

    def fake_upsert(slug: str, payload: dict[str, object], *, apply: bool) -> str:
        if slug == "o/b":
            raise github.GitHubAPIError("rules", 500, "boom")
        return f"upserted on {slug}"

    monkeypatch.setattr(github, "upsert_ruleset", fake_upsert)
    gen = cast(Iterator[str], rulesets.apply_rulesets(["o/a", "o/b"], root=POLICY_DATA_ROOT, apply=True))
    with pytest.raises(github.GitHubAPIError):
        for msg in gen:
            seen.append(msg)
    assert seen == ["upserted on o/a"]  # o/a's confirmation streamed before o/b failed


def test_apply_rulesets_value_error_is_clean_exit_not_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    # R2-4-5: a malformed ruleset (ValueError from render) exits 1 with a clean message, not a traceback.
    def boom(slugs: Sequence[str], **__: object) -> Never:
        raise ValueError("unknown patch key")

    monkeypatch.setattr(cli, "apply_rulesets", boom)
    assert cli.main(["apply-rulesets", "o/r", "--pin", "0"]) == 1


def test_command_run_missing_binary_raises_commanderror(monkeypatch: pytest.MonkeyPatch) -> None:
    # R2-4-4: a missing binary (FileNotFoundError) is surfaced as CommandError so main() catches it
    # (exit 2 + clean message), never a raw traceback.
    import subprocess

    from aviato import command

    def boom(*a: object, **k: object) -> Never:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(command.CommandError):
        command.run(["gh", "api", "x"])


def test_apply_rulesets_deferred_render_value_error_caught_through_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # R3-5-A/R3-1-GENLAZY: exercise the REAL apply_rulesets (not a call-time monkeypatch) with a
    # render that raises ValueError. Eager render means the error surfaces when the CLI calls
    # apply_rulesets (inside its try), so it's caught → clean exit 1, no traceback.
    from aviato import rulesets

    def boom(**__: object) -> Never:
        raise ValueError("malformed ruleset manifest")

    monkeypatch.setattr(rulesets, "render_all_rulesets", boom)
    # github.upsert_ruleset must never be reached (render fails first).
    assert cli.main(["apply-rulesets", "o/r", "--pin", "0"]) == 1


def test_apply_rulesets_renders_eagerly_at_call_not_on_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    # R3-1-GENLAZY: render runs at call time (old eager-list semantics), so a validation error can't
    # hide behind a caller that forgets to iterate.
    from aviato import rulesets

    def boom(**__: object) -> Never:
        raise ValueError("malformed")

    monkeypatch.setattr(rulesets, "render_all_rulesets", boom)
    with pytest.raises(ValueError):
        rulesets.apply_rulesets(["o/r"], root=POLICY_DATA_ROOT, apply=False)  # raises at call, before any iteration


def test_apply_rulesets_prints_loud_degraded_warning_only_after_successful_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "apply_rulesets",
        lambda *_, **__: iter([RulesetApplyResult("Created Common: release tag format on o/r", ("tag_name_pattern",))]),
    )

    assert cli.main(["apply-rulesets", "o/r", "--apply", "--pin", "0"]) == 0
    captured = capsys.readouterr()
    assert "Created Common: release tag format on o/r" in captured.out
    assert "DEGRADED" in captured.err
    assert "o/r" in captured.err
    assert "tag_name_pattern" in captured.err


def test_apply_rulesets_reports_earlier_success_before_later_failure_with_structured_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def stream(*_: object, **__: object) -> Iterator[RulesetApplyResult]:
        yield RulesetApplyResult("Created first on o/a", ())
        raise GitHubAPIError("repos/o/b/rulesets", 1, "boom")

    monkeypatch.setattr(cli, "apply_rulesets", stream)
    assert cli.main(["apply-rulesets", "o/a", "--repo", "o/b", "--apply", "--pin", "0"]) == 1
    captured = capsys.readouterr()
    assert "Created first on o/a" in captured.out
    assert "GitHub API error" in captured.err
    assert "transaction" not in (captured.out + captured.err).lower()
