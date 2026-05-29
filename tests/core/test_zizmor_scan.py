import json
import shutil as _shutil
import subprocess

import pytest

from aviato.plugins import zizmor_scan


def _fake_run(stdout: str, returncode: int = 0):
    def _run(command, *, cwd=None, check=True):
        return subprocess.CompletedProcess(command, returncode, stdout, "")
    return _run


def test_filters_to_gated_audits_only(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    findings = json.dumps([
        {"ident": "unpinned-uses", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
        {"ident": "template-injection", "locations": [{"symbolic": {"key": {"Local": {"given_path": "w.yml"}}}}]},
    ])
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run(findings))
    out = zizmor_scan.zizmor_uses_image_violations(tmp_path)
    assert any("unpinned-uses" in v for v in out)
    assert not any("template-injection" in v for v in out)


def test_empty_when_no_findings(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("[]\n", 0))
    assert zizmor_scan.zizmor_uses_image_violations(tmp_path) == []


def test_absent_workflow_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    assert zizmor_scan.zizmor_uses_image_violations(tmp_path / "nope") == []


def test_raises_when_zizmor_missing(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: False)
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        zizmor_scan.zizmor_uses_image_violations(tmp_path)


def test_raises_on_zizmor_error_exit(tmp_path, monkeypatch):
    (tmp_path / "w.yml").write_text("on: push\n", encoding="utf-8")
    monkeypatch.setattr(zizmor_scan, "_zizmor_available", lambda: True)
    monkeypatch.setattr(zizmor_scan, "run", _fake_run("", 1))
    with pytest.raises(zizmor_scan.ZizmorUnavailable):
        zizmor_scan.zizmor_uses_image_violations(tmp_path)


@pytest.mark.skipif(_shutil.which("zizmor") is None, reason="zizmor not installed")
def test_real_zizmor_flags_unpinned_and_passes_first_party(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "bad.yml").write_text(
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: docker/build-push-action@v5\n",
        encoding="utf-8",
    )
    out = zizmor_scan.zizmor_uses_image_violations(wf)
    assert any("unpinned-uses" in v for v in out), out
