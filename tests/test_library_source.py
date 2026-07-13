from __future__ import annotations

import io
import json
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

import aviato.library_source as library_source
from aviato.core.errors import AviatoError

SHA = "0123456789abcdef0123456789abcdef01234567"


def _archive(
    *,
    root: str = f"amattas-aviato-{SHA[:7]}",
    member: str = "aviato/library/profile.yaml",
    kind: str = "file",
    second_root: str | None = None,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(member if member.startswith("/") else f"{root}/{member}")
        body = b"name: profile\nidentity: aviato-profile/profile/v1\nworkflows: wf\nscaffold: sc\nsettings: set\n"
        if kind == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "/tmp/escape"
        else:
            info.size = len(body)
        archive.addfile(info, None if kind == "symlink" else io.BytesIO(body))
        if second_root is not None:
            extra = tarfile.TarInfo(f"{second_root}/README.md")
            extra.size = 1
            archive.addfile(extra, io.BytesIO(b"x"))
    return output.getvalue()


def _fake_run(monkeypatch: pytest.MonkeyPatch, archive_bytes: bytes, *, annotated: bool = False) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(command)
        calls.append(command)
        endpoint = command[2] if command[:2] == ["gh", "api"] else ""
        if endpoint.endswith(("/git/ref/tags/1", "/git/ref/tags/1.2.3")):
            obj_type = "tag" if annotated else "commit"
            obj_sha = "a" * 40 if annotated else SHA
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"object": {"type": obj_type, "sha": obj_sha}}), ""
            )
        if endpoint.endswith("/git/tags/" + "a" * 40):
            return subprocess.CompletedProcess(command, 0, json.dumps({"object": {"type": "commit", "sha": SHA}}), "")
        if "/tarball/" in endpoint:
            Path(command[command.index("--output") + 1]).write_bytes(archive_bytes)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "not found")

    monkeypatch.setattr(library_source, "run", fake)
    return calls


@pytest.mark.parametrize("pin", ["1", "1.2.3"])
@pytest.mark.parametrize("annotated", [False, True])
def test_fetch_library_registry_resolves_exact_commit_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, annotated: bool, pin: str
) -> None:
    calls = _fake_run(monkeypatch, _archive(), annotated=annotated)
    with library_source.fetch_library_registry("amattas/aviato", pin) as registry:
        extracted = registry.root
        assert registry.profile("profile").identity == "aviato-profile/profile/v1"
        assert extracted.exists()
    assert not extracted.exists()
    assert any(f"/tarball/{SHA}" in part for call in calls for part in call)


@pytest.mark.parametrize(
    "archive_bytes,match",
    [
        (_archive(member="../escape"), "unsafe"),
        (_archive(member="/absolute"), "absolute"),
        (_archive(kind="symlink"), "link"),
        (_archive(member="README.md"), "aviato/library"),
        (_archive(root="amattas-aviato-deadbee"), "commit"),
        (_archive(root=f"wrong-commit-{SHA[:7]}-spoof"), "commit"),
        (_archive(second_root="other-root"), "one commit-root"),
    ],
)
def test_fetch_library_registry_rejects_unsafe_or_mismatched_archives_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_bytes: bytes, match: str
) -> None:
    _fake_run(monkeypatch, archive_bytes)
    monkeypatch.setattr("aviato.library_source.tempfile.tempdir", str(tmp_path))
    before = set(tmp_path.iterdir())
    with pytest.raises(AviatoError, match=match), library_source.fetch_library_registry("amattas/aviato", "1"):
        pass
    assert set(tmp_path.iterdir()) == before


def test_fetch_library_registry_does_not_download_when_ref_is_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_run(monkeypatch, _archive())
    with (
        pytest.raises(AviatoError, match="resolve"),
        library_source.fetch_library_registry("amattas/aviato", "missing"),
    ):
        pass
    assert not any("/tarball/" in part for call in calls for part in call)
