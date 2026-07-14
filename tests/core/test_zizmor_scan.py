import json
import shutil as _shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import pytest

from aviato.paths import POLICY_DATA_ROOT
from aviato.plugins import zizmor_scan


def _scan(workflow_dir: Path) -> list[str]:
    return zizmor_scan.zizmor_uses_image_violations(workflow_dir, policy_root=POLICY_DATA_ROOT)


class _Run(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def _fake_run(stdout: str, returncode: int = 0) -> _Run:
    def _run(
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    return _run


def test_filters_to_gated_audits_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # finding 18 (operator decision): template-injection IS gated now; audits outside
    # the adopted set (e.g. artipacked) stay surfaced-but-non-gating.
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    findings = json.dumps(
        [
            {"ident": "unpinned-uses", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
            {"ident": "template-injection", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
            {"ident": "artipacked", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
        ]
    )
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run(findings))
    out = _scan(tmp_path)
    assert any("unpinned-uses" in v for v in out)
    assert any("template-injection" in v for v in out)
    assert not any("artipacked" in v for v in out)


def test_empty_when_no_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("[]\n", 0))
    assert _scan(tmp_path) == []


def test_absent_workflow_dir_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    assert _scan(tmp_path / "nope") == []


def test_raises_when_zizmor_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        _scan(tmp_path)


def test_raises_on_zizmor_error_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("", 1))
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        _scan(tmp_path)


def test_raises_on_non_list_toplevel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10-6: a future `{"findings": [...]}` shape must fail closed, not iterate keys and pass."""
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run('{"findings": []}\n', 0))
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        _scan(tmp_path)


def test_finding_location_tolerates_non_dict_symbolic() -> None:
    """R10-6: a non-dict `symbolic` must not raise AttributeError."""
    assert zizmor_scan._finding_location({"ident": "unpinned-uses", "locations": [{"symbolic": "x"}]}) == (
        "unpinned-uses"
    )


def _write(wf: Path, body: str) -> None:
    wf.mkdir(parents=True)
    (wf / "w.yml").write_text(body, encoding="utf-8")


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_flags_unpinned_container_image(tmp_path: Path) -> None:
    """R10-4: unpinned `container:` image must be gated (needs --persona=auditor)."""
    wf = tmp_path / ".github" / "workflows"
    _write(
        wf,
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    container:\n      image: alpine:3.19\n"
        "    steps:\n      - run: echo hi\n",
    )
    out = _scan(wf)
    assert any("unpinned-images" in v for v in out), out


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_ignores_inline_ignore(tmp_path: Path) -> None:
    """R10-8: a consumer's inline `# zizmor: ignore[...]` must NOT waive the gate (--no-ignores)."""
    wf = tmp_path / ".github" / "workflows"
    _write(
        wf,
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: docker/build-push-action@v5 # zizmor: ignore[unpinned-uses]\n",
    )
    out = _scan(wf)
    assert any("unpinned-uses" in v for v in out), out


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_first_party_not_false_flagged_under_auditor(tmp_path: Path) -> None:
    """The auditor persona must NOT loosen the ref-pin policy for actions/*, github/*, self-ref."""
    wf = tmp_path / ".github" / "workflows"
    _write(
        wf,
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: github/codeql-action@v3\n"
        "      - uses: amattas/aviato/.github/workflows/x.yml@v1\n",
    )
    out = _scan(wf)
    assert not any("unpinned-uses" in v for v in out), out


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_flags_unpinned_and_passes_first_party(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: docker/build-push-action@v5\n",
        encoding="utf-8",
    )
    out = _scan(wf)
    assert any("unpinned-uses" in v for v in out), out


def test_raises_on_unparseable_zizmor_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Garbage (non-JSON) zizmor stdout must fail closed (ZizmorUnavailable), not read as clean."""
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("panic: not json{", 0))
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        _scan(tmp_path)
