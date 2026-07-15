from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import ssl
import urllib.error
from typing import Any

import pytest


def _module() -> Any:
    return importlib.import_module("aviato.authority_verifier")


def _snapshot() -> dict[str, Any]:
    return {
        "schema": "aviato-protection-authority-snapshot/v1",
        "repository": {"database_id": 7, "node_id": "R_7", "full_name": "o/r", "default_branch": "main"},
        "classic": {"requires_pull_request": True},
        "repository_settings": {},
        "security": {"secret_scanning": True},
        "merge": {"allow_squash_merge": True},
        "rulesets": [{"id": 9, "rules": []}],
        "environments": {"pypi": {"can_admins_bypass": False, "reviewers": []}},
        "required_checks": [{"context": "ci", "app_id": 1, "integration_id": None, "source": "classic"}],
        "guard": {
            "intake": {"path": ".github/workflows/aviato-protection-checkpoint.yml", "blob_sha": "a" * 40},
            "release": {
                "repository": "amattas/aviato",
                "ref": "1.0.0",
                "path": ".github/workflows/reusable-release.yml",
                "blob_sha": "b" * 40,
            },
            "verifier": {
                "repository": "amattas/aviato",
                "ref": "1.0.0",
                "path": "aviato/authority_verifier.py",
                "blob_sha": "c" * 40,
            },
        },
    }


@pytest.mark.parametrize(
    "surface",
    (
        "repository",
        "classic",
        "repository_settings",
        "security",
        "merge",
        "rulesets",
        "environments",
        "required_checks",
        "guard",
    ),
)
def test_shared_verifier_rejects_drift_in_every_snapshot_surface(surface: str) -> None:
    expected = _snapshot()
    current = copy.deepcopy(expected)
    current[surface] = {"drift": True}
    with pytest.raises(ValueError, match="authority snapshot"):
        _module().require_exact_authority_snapshot(expected, current)


def test_shared_verifier_flattens_every_paginated_page_and_detects_late_duplicates() -> None:
    pages = [[{"id": value}] for value in range(1, 102)]
    flattened = _module().flatten_paginated_pages(pages, collection_key=None)
    assert [item["id"] for item in flattened] == list(range(1, 102))


def test_shared_verifier_is_stdlib_only_and_has_executable_cli() -> None:
    module = _module()
    assert module.AUTHORITY_SNAPSHOT_SCHEMA == "aviato-protection-authority-snapshot/v1"
    assert callable(module.main) and callable(module.collect_live_authority_snapshot)


def test_shared_verifier_selects_exact_signing_key_across_every_page() -> None:
    module = _module()
    pages = [[{"id": value, "key": f"ssh-ed25519 key-{value}"}] for value in range(1, 42)]
    assert module.select_unique_signing_key(pages, "41")["key"] == "ssh-ed25519 key-41"


def test_shared_verifier_rejects_duplicate_signing_key_across_pages() -> None:
    module = _module()
    with pytest.raises(ValueError, match="exactly one"):
        module.select_unique_signing_key(
            [[{"id": 7, "key": "ssh-ed25519 first"}], [{"id": "7", "key": "ssh-ed25519 second"}]],
            "7",
        )


def test_verifier_blob_hash_uses_git_blob_framing() -> None:
    body = b"print('bound')\n"
    expected = hashlib.sha1(b"blob " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()
    assert _module().git_blob_sha(body) == expected


def test_contents_decoder_accepts_only_crlf_wrapped_base64_and_binds_api_sha() -> None:
    module = _module()
    body = b"print('real GitHub payload')\n"
    encoded = module.base64.b64encode(body).decode("ascii")
    wrapped = "\r\n".join(encoded[index : index + 7] for index in range(0, len(encoded), 7))
    payload = {"encoding": "base64", "content": wrapped, "sha": module.git_blob_sha(body)}

    assert module.decode_contents_payload(payload, max_bytes=1_000) == body

    for invalid in (encoded + " ", encoded + "\t", encoded + "\v", encoded + "!", encoded[:-1]):
        with pytest.raises(ValueError):
            module.decode_contents_payload(
                {"encoding": "base64", "content": invalid, "sha": module.git_blob_sha(body)},
                max_bytes=1_000,
            )
    with pytest.raises(ValueError, match="too large"):
        module.decode_contents_payload(payload, max_bytes=3)
    with pytest.raises(ValueError, match="encoding"):
        module.decode_contents_payload({**payload, "encoding": "utf-8"}, max_bytes=1_000)
    with pytest.raises(ValueError, match="blob"):
        module.decode_contents_payload({**payload, "sha": "0" * 40}, max_bytes=1_000)


def test_verifier_github_reads_use_stdlib_https_and_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    calls: list[Any] = []

    class Response:
        headers: dict[str, str] = {}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"id": 7}'

        def geturl(self) -> str:
            return "https://api.github.com/repos/o/r"

    class Opener:
        def open(self, request: Any, timeout: int) -> Response:
            calls.append((request, timeout))
            return Response()

    monkeypatch.setenv("GH_TOKEN", "verifier-token")
    monkeypatch.setenv("PATH", "/attacker")
    monkeypatch.setattr(module, "_github_opener", lambda: Opener())
    assert module._gh("repos/o/r") == {"id": 7}
    request, timeout = calls[0]
    assert request.full_url == "https://api.github.com/repos/o/r"
    assert request.get_header("Authorization") == "Bearer verifier-token"
    assert timeout <= 30
    source = inspect.getsource(module._gh)
    assert "subprocess" not in source and "env=os.environ" not in source


def test_signature_verifier_uses_absolute_binary_and_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        captured.update(command=command, **kwargs)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/attacker")
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    module.verify_ssh_signature(b"message", b"signature", "alice", "ssh-ed25519 AAAA")
    assert captured["command"][0] == "/usr/bin/ssh-keygen"
    assert captured["env"] == {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}
    assert "must-not-leak" not in repr(captured)


def test_github_opener_ignores_proxy_and_malicious_ca_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    captured: dict[str, Any] = {}

    def fake_context(*_args: Any, **_kwargs: Any) -> ssl.SSLContext:
        captured["ssl_env"] = {key: module.os.environ.get(key) for key in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def fake_build_opener(*handlers: Any) -> Any:
        captured["handlers"] = handlers
        return object()

    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8080")
    monkeypatch.setenv("https_proxy", "http://attacker.invalid:8080")
    monkeypatch.setenv("SSL_CERT_FILE", "/attacker/ca.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/attacker/certs")
    monkeypatch.setattr(module.ssl, "create_default_context", fake_context)
    monkeypatch.setattr(module.urllib.request, "build_opener", fake_build_opener)
    module._github_opener()

    assert captured["ssl_env"] == {"SSL_CERT_FILE": None, "SSL_CERT_DIR": None}
    proxy = next(handler for handler in captured["handlers"] if isinstance(handler, module.urllib.request.ProxyHandler))
    assert proxy.proxies == {}
    assert any(isinstance(handler, module.DenyRedirectHandler) for handler in captured["handlers"])


def test_github_reader_denies_redirect_without_forwarding_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    requests: list[Any] = []

    class RedirectingOpener:
        def open(self, request: Any, timeout: int) -> Any:
            requests.append(request)
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect denied",
                {"Location": "https://attacker.invalid/steal"},
                None,
            )

    monkeypatch.setenv("GH_TOKEN", "verifier-token")
    monkeypatch.setattr(module, "_github_opener", lambda: RedirectingOpener())
    with pytest.raises(urllib.error.HTTPError):
        module._gh("repos/o/r")
    assert len(requests) == 1
    assert requests[0].full_url.startswith("https://api.github.com/")
    assert requests[0].get_header("Authorization") == "Bearer verifier-token"


def test_full_verifier_bootstraps_clear_ambient_network_and_python_environment() -> None:
    from aviato.paths import REPO_ROOT

    paths = (
        REPO_ROOT / ".github/workflows/reusable-release.yml",
        REPO_ROOT / ".github/workflows/reusable-docker-ghcr.yml",
        REPO_ROOT / ".github/workflows/reusable-app-store-connect.yml",
        REPO_ROOT / ".github/workflows/reusable-docs-pages.yml",
        REPO_ROOT / "aviato/library/workflow-fragments/pypi-publish.yml",
    )
    for path in paths:
        body = path.read_text(encoding="utf-8")
        assert "/usr/bin/env -i" in body, path
        assert "PATH=/usr/bin:/bin" in body, path
        assert "PYTHONPATH" not in body, path
        assert "SSL_CERT_FILE" not in body, path


def test_live_collector_explicitly_excludes_parent_rulesets() -> None:
    calls: list[tuple[str, bool]] = []
    expected = _snapshot()

    def read(endpoint: str, paginated: bool) -> Any:
        calls.append((endpoint, paginated))
        if endpoint == "repos/o/r":
            return {
                "id": 7,
                "node_id": "R_7",
                "full_name": "o/r",
                "default_branch": "main",
                "allow_merge_commit": False,
                "allow_squash_merge": True,
                "allow_rebase_merge": False,
            }
        if "/rulesets?" in endpoint or "/rules/branches/" in endpoint:
            return [[]]
        if endpoint.endswith("/protection"):
            return {}
        if "/environments?" in endpoint:
            return [{"environments": []}]
        if "/contents/" in endpoint:
            descriptor = next(item for item in expected["guard"].values() if item["path"] in endpoint)
            return {"sha": descriptor["blob_sha"]}
        raise AssertionError(endpoint)

    _module().collect_live_authority_snapshot("o/r", expected, read)
    ruleset_calls = [endpoint for endpoint, _ in calls if "/rulesets?" in endpoint]
    assert ruleset_calls == ["repos/o/r/rulesets?includes_parents=false&per_page=100"]
