from __future__ import annotations

from pathlib import Path

import pytest

from aviato import cli
from aviato.github import GitHubAPIError


def _patch_apply(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture every apply_rulesets call instead of touching GitHub."""
    calls: list[dict] = []

    def fake(slugs, *, apply, required_approvals=None, extra_status_checks=None):
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
    rc = cli.main(["apply-rulesets", "o/one", "--repo", "o/two", "--repos-file", str(repos_file)])
    assert rc == 0
    assert calls[0]["slugs"] == ["o/one", "o/two", "o/three", "o/four"]
    assert calls[0]["apply"] is False  # default is dry-run


def test_apply_rulesets_requires_a_slug(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["apply-rulesets"])
    assert rc == 2
    assert "at least one repository slug is required" in capsys.readouterr().err


def test_apply_rulesets_warns_on_direct_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _patch_apply(monkeypatch)
    rc = cli.main(["apply-rulesets", "o/r", "--apply"])
    assert rc == 0
    assert calls[0]["apply"] is True
    err = capsys.readouterr().err
    assert "WARNING" in err and "reconcile" in err  # §5.7 nudge toward the gated flow


def test_apply_rulesets_maps_github_error_to_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a, **k):
        raise GitHubAPIError("repos/o/r/rulesets", 1, "nope")

    monkeypatch.setattr(cli, "apply_rulesets", boom)
    rc = cli.main(["apply-rulesets", "o/r", "--apply"])
    assert rc == 1
    assert "GitHub API error" in capsys.readouterr().err


def test_apply_rulesets_unknown_profile_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A bad --profile fails composition (AviatoError) and must be a clean exit-2 operator
    # error, not an uncaught traceback — and must NOT reach apply_rulesets.
    def must_not_run(*a, **k):
        raise AssertionError("apply_rulesets must not be called when the profile is invalid")

    monkeypatch.setattr(cli, "apply_rulesets", must_not_run)
    rc = cli.main(["apply-rulesets", "o/r", "--profile", "no-such-profile", "--apply"])
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


def test_apply_rulesets_missing_repos_file_is_clean_error(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
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
