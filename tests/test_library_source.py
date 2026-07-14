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
MOVED_SHA = "89abcdef0123456789abcdef0123456789abcdef"
ANNOTATED_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BRANCH_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
REPOSITORY = "amattas/aviato"
DEFAULT_BRANCH = "main"


def _repository_payload(
    *,
    full_name: str = REPOSITORY,
    default_branch: str = DEFAULT_BRANCH,
) -> dict[str, object]:
    return {
        "id": 123456789,
        "node_id": "R_kgDOAviato",
        "full_name": full_name,
        "default_branch": default_branch,
    }


def _completed(
    endpoint: str,
    *,
    status: int = 0,
    payload: object | None = None,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    stdout = "" if payload is None else json.dumps(payload)
    return subprocess.CompletedProcess(["gh", "api", endpoint], status, stdout, stderr)


def _archive(
    *,
    root: str = f"amattas-aviato-{SHA[:7]}",
    member: str = "aviato/library/profile.yaml",
    kind: str = "file",
    second_root: str | None = None,
    identity: str = "aviato-profile/profile/v1",
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(member if member.startswith("/") else f"{root}/{member}")
        body = (
            f"name: profile\nidentity: {identity}\nworkflows: wf\nscaffold: sc\nsettings: set\n".encode()
        )
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
        if endpoint == f"repos/{REPOSITORY}":
            return _completed(endpoint, payload=_repository_payload())
        if endpoint == f"repos/{REPOSITORY}/git/ref/heads/{DEFAULT_BRANCH}":
            return _ref_response(endpoint, "commit", SHA)
        if endpoint.endswith(("/git/ref/tags/1", "/git/ref/tags/1.2.3")):
            obj_type = "tag" if annotated else "commit"
            obj_sha = "a" * 40 if annotated else SHA
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"object": {"type": obj_type, "sha": obj_sha}}), ""
            )
        if endpoint.endswith("/git/tags/" + "a" * 40):
            return subprocess.CompletedProcess(command, 0, json.dumps({"object": {"type": "commit", "sha": SHA}}), "")
        if "/tarball/" in endpoint:
            raise AssertionError("archive downloads must use the binary path helper without CLI output flags")
        return subprocess.CompletedProcess(command, 1, "", "gh: Not Found (HTTP 404)")

    def fake_download(
        command: Sequence[str],
        destination: str | Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        command = list(command)
        calls.append(command)
        endpoint = command[2] if command[:2] == ["gh", "api"] else ""
        assert command == ["gh", "api", endpoint]
        assert endpoint == f"repos/{REPOSITORY}/tarball/{SHA}"
        Path(destination).write_bytes(archive_bytes)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(library_source, "run", fake, raising=False)
    monkeypatch.setattr(library_source, "run_to_path", fake_download, raising=False)
    monkeypatch.setattr(library_source.github, "run", fake)
    return calls


def _install_api(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, subprocess.CompletedProcess[str] | list[subprocess.CompletedProcess[str]]],
    *,
    archives: dict[str, bytes] | None = None,
) -> list[str]:
    """Install one correlated fake for repository, ref, peel, and tarball reads."""

    queued = {endpoint: value if isinstance(value, list) else [value] for endpoint, value in responses.items()}
    calls: list[str] = []

    def fake(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = list(command)
        endpoint = command[2] if command[:2] == ["gh", "api"] else ""
        calls.append(endpoint)
        if "/tarball/" in endpoint:
            raise AssertionError("archive downloads must use the binary path helper without CLI output flags")
        queue = queued.get(endpoint)
        if not queue:
            raise AssertionError(f"unexpected GitHub API read: {endpoint}")
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        return subprocess.CompletedProcess(command, response.returncode, response.stdout, response.stderr)

    def fake_download(
        command: Sequence[str],
        destination: str | Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        command = list(command)
        endpoint = command[2] if command[:2] == ["gh", "api"] else ""
        calls.append(endpoint)
        assert command == ["gh", "api", endpoint]
        if archives is None or endpoint not in archives:
            raise AssertionError(f"unexpected archive download: {endpoint}")
        Path(destination).write_bytes(archives[endpoint])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(library_source, "run", fake, raising=False)
    monkeypatch.setattr(library_source, "run_to_path", fake_download, raising=False)
    monkeypatch.setattr(library_source.github, "run", fake)
    return calls


def _repository_response(
    *,
    endpoint: str = f"repos/{REPOSITORY}",
    full_name: str = REPOSITORY,
) -> subprocess.CompletedProcess[str]:
    return _completed(endpoint, payload=_repository_payload(full_name=full_name))


def _ref_response(endpoint: str, object_type: str, sha: str) -> subprocess.CompletedProcess[str]:
    return _completed(endpoint, payload={"object": {"type": object_type, "sha": sha}})


def _not_found(endpoint: str) -> subprocess.CompletedProcess[str]:
    return _completed(endpoint, status=1, stderr="gh: Not Found (HTTP 404)")


def _accessible_repository_responses(
    *,
    metadata_endpoint: str = f"repos/{REPOSITORY}",
    canonical_name: str = REPOSITORY,
) -> dict[str, subprocess.CompletedProcess[str]]:
    default_ref_endpoint = f"repos/{canonical_name}/git/ref/heads/{DEFAULT_BRANCH}"
    return {
        metadata_endpoint: _repository_response(endpoint=metadata_endpoint, full_name=canonical_name),
        default_ref_endpoint: _ref_response(default_ref_endpoint, "commit", SHA),
    }


def test_accessible_repository_tag_404_may_fall_back_to_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{repository_endpoint}/git/ref/tags/v1"
    branch_endpoint = f"{repository_endpoint}/git/ref/heads/v1"
    _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(),
            tag_endpoint: _not_found(tag_endpoint),
            branch_endpoint: _ref_response(branch_endpoint, "commit", BRANCH_SHA),
        },
    )

    resolved = library_source.resolve_library_ref(REPOSITORY, "v1")

    assert resolved.ref_kind.value == "branch"
    assert resolved.requested_pin == "v1"
    assert resolved.object_sha == BRANCH_SHA
    assert resolved.commit_sha == BRANCH_SHA
    assert resolved.repository_identity.full_name == REPOSITORY
    assert resolved.repository_identity.database_id == 123456789


def test_tag_wins_when_tag_and_branch_share_a_name(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{repository_endpoint}/git/ref/tags/shared"
    calls = _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(),
            tag_endpoint: _ref_response(tag_endpoint, "commit", SHA),
        },
    )

    resolved = library_source.resolve_library_ref(REPOSITORY, "shared")

    assert resolved.ref_kind.value == "tag"
    assert resolved.commit_sha == SHA
    assert not any("/git/ref/heads/shared" in endpoint for endpoint in calls)


@pytest.mark.parametrize(
    ("repository_result", "tag_result"),
    [
        (
            _completed(f"repos/{REPOSITORY}", status=1, stderr="gh: Not Found (HTTP 404)"),
            None,
        ),
        (_completed(f"repos/{REPOSITORY}", payload={"message": "Not Found"}), None),
        (
            _repository_response(),
            _completed(
                f"repos/{REPOSITORY}/git/ref/tags/private",
                status=1,
                stderr="gh: Resource not found by integration (HTTP 403)",
            ),
        ),
    ],
    ids=("hidden-repository", "ambiguous-repository-payload", "ambiguous-tag-404"),
)
def test_hidden_or_ambiguous_404_never_falls_back_to_branch(
    monkeypatch: pytest.MonkeyPatch,
    repository_result: subprocess.CompletedProcess[str],
    tag_result: subprocess.CompletedProcess[str] | None,
) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    responses: dict[str, subprocess.CompletedProcess[str]] = {repository_endpoint: repository_result}
    if tag_result is not None:
        responses.update(_accessible_repository_responses())
        responses[f"{repository_endpoint}/git/ref/tags/private"] = tag_result
    calls = _install_api(monkeypatch, responses)

    with pytest.raises(AviatoError):
        library_source.resolve_library_ref(REPOSITORY, "private")

    assert not any("/git/ref/heads/private" in endpoint for endpoint in calls)


def test_metadata_visible_but_git_content_hidden_404_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    default_ref_endpoint = f"{repository_endpoint}/git/ref/heads/{DEFAULT_BRANCH}"
    calls = _install_api(
        monkeypatch,
        {
            repository_endpoint: _repository_response(),
            default_ref_endpoint: _not_found(default_ref_endpoint),
        },
    )

    with pytest.raises(AviatoError, match="access|default branch|content"):
        library_source.resolve_library_ref(REPOSITORY, "private")

    assert not any("/git/ref/tags/private" in endpoint for endpoint in calls)
    assert not any("/git/ref/heads/private" in endpoint for endpoint in calls)


@pytest.mark.parametrize(
    "default_ref_result",
    [
        _completed(
            f"repos/{REPOSITORY}/git/ref/heads/{DEFAULT_BRANCH}",
            status=1,
            stderr="gh: Forbidden (HTTP 403)",
        ),
        _completed(f"repos/{REPOSITORY}/git/ref/heads/{DEFAULT_BRANCH}", payload={"object": {}}),
        _ref_response(f"repos/{REPOSITORY}/git/ref/heads/{DEFAULT_BRANCH}", "tag", ANNOTATED_SHA),
    ],
    ids=("error", "malformed", "non-commit"),
)
def test_default_branch_access_probe_must_be_a_valid_commit(
    monkeypatch: pytest.MonkeyPatch,
    default_ref_result: subprocess.CompletedProcess[str],
) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    default_ref_endpoint = f"{repository_endpoint}/git/ref/heads/{DEFAULT_BRANCH}"
    calls = _install_api(
        monkeypatch,
        {
            repository_endpoint: _repository_response(),
            default_ref_endpoint: default_ref_result,
        },
    )

    with pytest.raises(AviatoError, match="access|default branch|content"):
        library_source.resolve_library_ref(REPOSITORY, "private")

    assert not any("/git/ref/tags/private" in endpoint for endpoint in calls)


@pytest.mark.parametrize("default_branch", ["", 7])
def test_repository_metadata_requires_valid_default_branch(
    monkeypatch: pytest.MonkeyPatch,
    default_branch: object,
) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    payload = _repository_payload()
    payload["default_branch"] = default_branch
    calls = _install_api(
        monkeypatch,
        {repository_endpoint: _completed(repository_endpoint, payload=payload)},
    )

    with pytest.raises(AviatoError, match="repository|default branch"):
        library_source.resolve_library_ref(REPOSITORY, "v1")

    assert calls == [repository_endpoint]


def test_annotated_tag_peel_failure_never_falls_back_to_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{repository_endpoint}/git/ref/tags/v1"
    peel_endpoint = f"{repository_endpoint}/git/tags/{ANNOTATED_SHA}"
    calls = _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(),
            tag_endpoint: _ref_response(tag_endpoint, "tag", ANNOTATED_SHA),
            peel_endpoint: _completed(peel_endpoint, status=1, stderr="gh: Service unavailable (HTTP 503)"),
        },
    )

    with pytest.raises(AviatoError, match="peel|annotated"):
        library_source.resolve_library_ref(REPOSITORY, "v1")

    assert not any("/git/ref/heads/v1" in endpoint for endpoint in calls)


def test_ref_movement_after_resolution_still_fetches_original_commit_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{repository_endpoint}/git/ref/tags/moving"
    original_archive_endpoint = f"{repository_endpoint}/tarball/{SHA}"
    moved_archive_endpoint = f"{repository_endpoint}/tarball/{MOVED_SHA}"
    calls = _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(),
            tag_endpoint: [
                _ref_response(tag_endpoint, "commit", SHA),
                _ref_response(tag_endpoint, "commit", MOVED_SHA),
            ],
        },
        archives={
            original_archive_endpoint: _archive(identity="aviato-profile/original/v1"),
            moved_archive_endpoint: _archive(
                root=f"amattas-aviato-{MOVED_SHA[:7]}", identity="aviato-profile/moved/v1"
            ),
        },
    )

    with library_source.fetch_library_registry(REPOSITORY, "moving") as registry:
        assert registry.profile("profile").identity == "aviato-profile/original/v1"

    assert calls.count(tag_endpoint) == 1
    assert original_archive_endpoint in calls
    assert moved_archive_endpoint not in calls


@pytest.mark.parametrize(
    "archive_root",
    ["amattas-aviato-deadbee", f"other-repository-{SHA[:7]}"],
    ids=("wrong-commit", "wrong-repository-same-commit-prefix"),
)
def test_archive_identity_must_match_the_resolved_commit(
    monkeypatch: pytest.MonkeyPatch,
    archive_root: str,
) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{repository_endpoint}/git/ref/tags/v1"
    archive_endpoint = f"{repository_endpoint}/tarball/{SHA}"
    _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(),
            tag_endpoint: _ref_response(tag_endpoint, "commit", SHA),
        },
        archives={archive_endpoint: _archive(root=archive_root)},
    )

    with pytest.raises(AviatoError, match="resolved commit"), library_source.fetch_library_registry(REPOSITORY, "v1"):
        pass


def test_repository_identity_is_correlated_and_canonical_for_ref_and_archive_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = "Amattas/Aviato"
    metadata_endpoint = f"repos/{requested}"
    canonical_endpoint = f"repos/{REPOSITORY}"
    tag_endpoint = f"{canonical_endpoint}/git/ref/tags/v1"
    archive_endpoint = f"{canonical_endpoint}/tarball/{SHA}"
    calls = _install_api(
        monkeypatch,
        {
            **_accessible_repository_responses(
                metadata_endpoint=metadata_endpoint,
                canonical_name=REPOSITORY,
            ),
            tag_endpoint: _ref_response(tag_endpoint, "commit", SHA),
        },
        archives={archive_endpoint: _archive()},
    )

    resolved = library_source.resolve_library_ref(requested, "v1")
    with library_source.fetch_library_registry(requested, "v1") as registry:
        assert registry.profile("profile").identity == "aviato-profile/profile/v1"

    assert resolved.repository_identity.full_name == REPOSITORY
    assert tag_endpoint in calls
    assert archive_endpoint in calls
    assert not any(endpoint.startswith(f"repos/{requested}/git/") for endpoint in calls)
    assert not any(endpoint.startswith(f"repos/{requested}/tarball/") for endpoint in calls)


def test_unrelated_repository_identity_is_rejected_before_ref_or_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_endpoint = f"repos/{REPOSITORY}"
    calls = _install_api(
        monkeypatch,
        {repository_endpoint: _repository_response(full_name="unrelated/library")},
    )

    with pytest.raises(AviatoError, match="identity|repository"):
        library_source.resolve_library_ref(REPOSITORY, "v1")

    assert calls == [repository_endpoint]


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
