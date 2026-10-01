"""Unit tests for `relay verify-release` (relay/verify_release.py).

All network access is mocked: no test may touch the network, $HOME, or the
real GitHub API. The Scoop manifest is redirected at a tmp file via the
``scoop_path`` seam.
"""

import base64
import json
from pathlib import Path
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.verify_release import (
    VerifyError,
    normalize_version,
    parse_formula,
    parse_sha256sums,
    run_verify_release,
)

VER = "2.5.0"
WHEEL = f"relay_cli-{VER}-py3-none-any.whl"
SDIST = f"relay_cli-{VER}.tar.gz"
WHEEL_HASH = "a" * 64
SDIST_HASH = "b" * 64

RELEASE_JSON = {
    "tag_name": f"v{VER}",
    "name": f"v{VER}",
    "assets": [
        {"name": WHEEL, "browser_download_url": f"https://example.com/{WHEEL}"},
        {"name": SDIST, "browser_download_url": f"https://example.com/{SDIST}"},
        {
            "name": "SHA256SUMS",
            "browser_download_url": "https://example.com/SHA256SUMS",
        },
    ],
}

SHA256SUMS_TEXT = f"{WHEEL_HASH}  {WHEEL}\n{SDIST_HASH}  {SDIST}\n"

FORMULA_TEXT = (
    '  url "https://github.com/Fiqqar/Relay/releases/download/'
    f'v{VER}/{SDIST}"\n'
    f'  sha256 "{SDIST_HASH}"\n'
)


def _formula_api_payload():
    return {
        "content": base64.b64encode(FORMULA_TEXT.encode("utf-8")).decode("ascii"),
        "encoding": "base64",
    }


def _write_scoop_manifest(path: Path, version: str = VER, wheel_hash: str = WHEEL_HASH) -> Path:
    manifest = {
        "version": version,
        "url": f"https://github.com/Fiqqar/Relay/releases/download/"
        f"v{version}/relay_cli-{version}-py3-none-any.whl",
        "hash": f"sha256:{wheel_hash}",
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture
def healthy_mocks(tmp_path):
    """All remote calls succeed and the local Scoop manifest matches."""
    scoop = _write_scoop_manifest(tmp_path / "relay.json")
    with (
        mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(RELEASE_JSON)
            ),
        ),
        mock.patch(
            "relay.verify_release._fetch_text",
            return_value=SHA256SUMS_TEXT,
        ),
        mock.patch(
            "relay.verify_release._fetch_bytes",
            return_value=b"wheel-bytes",
        ),
    ):
        yield scoop


class TestNormalizeVersion:
    def test_plain_version_passes_through(self):
        assert normalize_version("2.5.0") == "2.5.0"

    def test_v_prefix_is_stripped(self):
        assert normalize_version("v2.5.0") == "2.5.0"

    def test_whitespace_is_stripped(self):
        assert normalize_version("  v2.5.0  ") == "2.5.0"

    def test_none_means_installed_version(self):
        with mock.patch("relay.verify_release.__version__", "9.9.9"):
            assert normalize_version(None) == "9.9.9"

    def test_bad_shape_raises(self):
        for bad in ("", "v", "1.2", "abc", "1.2.3.4.5.6"):
            with pytest.raises(VerifyError):
                normalize_version(bad)


class TestParseHelpers:
    def test_parse_sha256sums(self):
        parsed = parse_sha256sums(SHA256SUMS_TEXT)
        assert parsed == {WHEEL: WHEEL_HASH, SDIST: SDIST_HASH}

    def test_parse_sha256sums_ignores_blank_lines(self):
        parsed = parse_sha256sums("\n" + SHA256SUMS_TEXT + "\n")
        assert parsed[WHEEL] == WHEEL_HASH

    def test_parse_sha256sums_rejects_garbage(self):
        with pytest.raises(VerifyError):
            parse_sha256sums("not a checksum line\n")

    def test_parse_formula(self):
        url, sha = parse_formula(FORMULA_TEXT)
        assert url.endswith(f"v{VER}/{SDIST}")
        assert sha == SDIST_HASH

    def test_parse_formula_rejects_garbage(self):
        with pytest.raises(VerifyError):
            parse_formula("class Relay < Formula\nend\n")


class TestRunVerifyRelease:
    def test_all_checks_pass(self, healthy_mocks, capsys):
        assert run_verify_release(VER, scoop_path=healthy_mocks) == 0
        out = capsys.readouterr().out
        assert "all good" in out

    def test_v_prefixed_version_passes(self, healthy_mocks, capsys):
        assert run_verify_release("v2.5.0", scoop_path=healthy_mocks) == 0
        assert "all good" in capsys.readouterr().out

    def test_default_version_is_installed(self, healthy_mocks, capsys):
        with mock.patch("relay.verify_release.__version__", VER):
            assert run_verify_release(None, scoop_path=healthy_mocks) == 0
        assert "all good" in capsys.readouterr().out

    def test_missing_tag_fails(self, healthy_mocks, capsys):
        import urllib.error

        err = urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)
        with mock.patch("relay.verify_release._fetch_json", side_effect=err):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "tag" in capsys.readouterr().out.lower()

    def test_wrong_release_title_fails(self, healthy_mocks, capsys):
        bad = dict(RELEASE_JSON, name="Release 2.5.0")
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(bad)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "Release 2.5.0" in capsys.readouterr().out

    def test_missing_asset_fails(self, healthy_mocks, capsys):
        bad = dict(RELEASE_JSON)
        bad["assets"] = [a for a in bad["assets"] if a["name"] != WHEEL]
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(bad)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert WHEEL in capsys.readouterr().out

    def test_scoop_version_mismatch_fails(self, healthy_mocks, tmp_path, capsys):
        stale = _write_scoop_manifest(tmp_path / "stale.json", version="2.4.0")
        assert run_verify_release(VER, scoop_path=stale) == 1
        assert "scoop" in capsys.readouterr().out.lower()

    def test_scoop_hash_mismatch_fails(self, healthy_mocks, tmp_path, capsys):
        wrong = _write_scoop_manifest(tmp_path / "wrong.json", wheel_hash="c" * 64)
        assert run_verify_release(VER, scoop_path=wrong) == 1
        assert "scoop" in capsys.readouterr().out.lower()

    def test_brew_hash_mismatch_fails(self, healthy_mocks, capsys):
        doctored = FORMULA_TEXT.replace(SDIST_HASH, "d" * 64)
        payload = {
            "content": base64.b64encode(doctored.encode()).decode("ascii"),
            "encoding": "base64",
        }
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                payload if "homebrew-Relay" in url else dict(RELEASE_JSON)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "homebrew" in capsys.readouterr().out.lower()

    def test_network_error_never_tracebacks(self, healthy_mocks, capsys):
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=OSError("connection refused"),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        out = capsys.readouterr().out
        assert "Traceback" not in out

    def test_invalid_version_returns_one(self, healthy_mocks, capsys):
        assert run_verify_release("bogus", scoop_path=healthy_mocks) == 1
        assert "version" in capsys.readouterr().out.lower()

    def test_json_output_is_machine_readable(self, healthy_mocks, capsys):
        assert run_verify_release(VER, scoop_path=healthy_mocks, json_output=True) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["version"] == VER
        assert report["exit_code"] == 0
        assert all(c["status"] == "ok" for c in report["checks"])

    def test_download_recomputes_the_wheel_hash(self, healthy_mocks, capsys):
        import hashlib

        digest = hashlib.sha256(b"wheel-bytes").hexdigest()
        sums = f"{digest}  {WHEEL}\n{SDIST_HASH}  {SDIST}\n"
        with mock.patch("relay.verify_release._fetch_text", return_value=sums):
            assert (
                run_verify_release(VER, scoop_path=healthy_mocks, download=True)
                == 1  # local manifest still carries WHEEL_HASH, not digest
            )
        assert "download" in capsys.readouterr().out.lower()

    def test_download_match_passes(self, tmp_path, capsys):
        import hashlib

        digest = hashlib.sha256(b"wheel-bytes").hexdigest()
        sums = f"{digest}  {WHEEL}\n{SDIST_HASH}  {SDIST}\n"
        scoop = _write_scoop_manifest(tmp_path / "relay.json", wheel_hash=digest)
        with (
            mock.patch(
                "relay.verify_release._fetch_json",
                side_effect=lambda url, timeout=30: (
                    _formula_api_payload() if "homebrew-Relay" in url else dict(RELEASE_JSON)
                ),
            ),
            mock.patch("relay.verify_release._fetch_text", return_value=sums),
            mock.patch("relay.verify_release._fetch_bytes", return_value=b"wheel-bytes"),
        ):
            assert run_verify_release(VER, scoop_path=scoop, download=True) == 0
        assert "all good" in capsys.readouterr().out


class TestFetchHelpers:
    """The real HTTP helpers, with urlopen mocked (no network)."""

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            if limit is not None and limit >= 0:
                return self._body[:limit]
            return self._body

    def test_fetch_json_decodes(self):
        from relay import verify_release as vr

        with mock.patch(
            "urllib.request.urlopen",
            return_value=self._FakeResp(b'{"tag_name": "v2.5.0"}'),
        ):
            assert vr._fetch_json("https://api.github.com/x") == {"tag_name": "v2.5.0"}

    def test_fetch_json_rejects_oversize_body(self):
        from relay import verify_release as vr

        big = b"x" * (vr._MAX_JSON_BYTES + 1)
        with (
            mock.patch("urllib.request.urlopen", return_value=self._FakeResp(big)),
            pytest.raises(VerifyError),
        ):
            vr._fetch_json("https://api.github.com/x")

    def test_fetch_text_decodes(self):
        from relay import verify_release as vr

        with mock.patch(
            "urllib.request.urlopen",
            return_value=self._FakeResp(b"abc  file\n"),
        ):
            assert vr._fetch_text("https://example.com/SHA256SUMS") == "abc  file\n"

    def test_fetch_text_rejects_oversize_body(self):
        from relay import verify_release as vr

        big = b"x" * (vr._MAX_TEXT_BYTES + 1)
        with (
            mock.patch("urllib.request.urlopen", return_value=self._FakeResp(big)),
            pytest.raises(VerifyError),
        ):
            vr._fetch_text("https://example.com/SHA256SUMS")

    def test_fetch_bytes_round_trips(self):
        from relay import verify_release as vr

        with mock.patch(
            "urllib.request.urlopen",
            return_value=self._FakeResp(b"wheel-bytes"),
        ):
            assert vr._fetch_bytes("https://example.com/w.whl") == b"wheel-bytes"

    def test_fetch_bytes_rejects_oversize_body(self):
        from relay import verify_release as vr

        with (
            mock.patch.object(vr, "_MAX_WHEEL_BYTES", 10),
            mock.patch("urllib.request.urlopen", return_value=self._FakeResp(b"x" * 11)),
            pytest.raises(VerifyError),
        ):
            vr._fetch_bytes("https://example.com/w.whl")

    def test_headers_carry_token_when_set(self):
        from relay import verify_release as vr

        with mock.patch("relay.verify_release.github_token", return_value="sekret"):
            headers = vr._headers("application/vnd.github+json")
        assert headers["Authorization"] == "Bearer sekret"

    def test_headers_skip_auth_without_token(self):
        from relay import verify_release as vr

        with mock.patch("relay.verify_release.github_token", return_value=None):
            headers = vr._headers("*/*")
        assert "Authorization" not in headers

    def test_default_scoop_path_points_at_the_bucket(self):
        from relay import verify_release as vr

        path = vr._default_scoop_path()
        assert path.name == "relay.json"
        assert path.parent.name == "bucket"

    def test_fetch_text_follows_redirect_without_credentials(self):
        import urllib.error
        import urllib.request

        from relay import verify_release as vr

        redirect = urllib.error.HTTPError(
            "https://example.com/SHA256SUMS",
            302,
            "Found",
            {"Location": "https://cdn.example/SHA256SUMS"},
            None,
        )
        seen = []

        def fake_urlopen(req, timeout=30):
            seen.append(req)
            if len(seen) == 1:
                raise redirect
            return self._FakeResp(b"abc  file\n")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            assert vr._fetch_text("https://example.com/SHA256SUMS") == "abc  file\n"
        assert seen[1].full_url == "https://cdn.example/SHA256SUMS"
        for req in seen:
            assert req.get_header("Authorization") is None

    def test_fetch_bytes_follows_redirect_without_credentials(self):
        import urllib.error

        from relay import verify_release as vr

        redirect = urllib.error.HTTPError(
            "https://example.com/w.whl",
            302,
            "Found",
            {"Location": "https://cdn.example/w.whl"},
            None,
        )
        seen = []

        def fake_urlopen(req, timeout=30):
            seen.append(req)
            if len(seen) == 1:
                raise redirect
            return self._FakeResp(b"wheel-bytes")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            assert vr._fetch_bytes("https://example.com/w.whl") == b"wheel-bytes"
        for req in seen:
            assert req.get_header("Authorization") is None

    def test_fetch_text_rejects_redirect_loops(self):
        import urllib.error

        from relay import verify_release as vr

        redirect = urllib.error.HTTPError(
            "https://example.com/SHA256SUMS",
            302,
            "Found",
            {"Location": "https://example.com/SHA256SUMS"},
            None,
        )
        with (
            mock.patch("urllib.request.urlopen", side_effect=redirect),
            pytest.raises(VerifyError, match="too many redirects"),
        ):
            vr._fetch_text("https://example.com/SHA256SUMS")

    def test_fetch_text_forwards_non_redirect_errors(self):
        import urllib.error

        from relay import verify_release as vr

        missing = urllib.error.HTTPError(
            "https://example.com/SHA256SUMS", 404, "Not Found", {}, None
        )
        with (
            mock.patch("urllib.request.urlopen", side_effect=missing),
            pytest.raises(urllib.error.HTTPError),
        ):
            vr._fetch_text("https://example.com/SHA256SUMS")


class TestDecodeFormulaPayload:
    def test_rejects_non_base64_encoding(self):
        from relay import verify_release as vr

        with pytest.raises(VerifyError):
            vr._decode_formula_payload({"content": "eA==", "encoding": "utf-8"})

    def test_rejects_empty_content(self):
        from relay import verify_release as vr

        with pytest.raises(VerifyError):
            vr._decode_formula_payload({"content": "  ", "encoding": "base64"})

    def test_rejects_corrupt_content(self):
        from relay import verify_release as vr

        with pytest.raises(VerifyError):
            vr._decode_formula_payload({"content": "!!!not-base64!!!", "encoding": "base64"})


class TestParseEdgeCases:
    def test_sha256sums_rejects_bad_digest(self):
        with pytest.raises(VerifyError):
            parse_sha256sums(f"{'z' * 64}  {WHEEL}\n")

    def test_sha256sums_rejects_empty(self):
        with pytest.raises(VerifyError):
            parse_sha256sums("\n   \n")

    def test_formula_rejects_bad_sha(self):
        with pytest.raises(VerifyError):
            parse_formula(f'url "https://example.com/x"\nsha256 "{"q" * 64}"\n')


class TestRunEdgeCases:
    def test_non_404_api_error_fails(self, healthy_mocks, capsys):
        import urllib.error

        err = urllib.error.HTTPError("https://api.github.com/x", 500, "Server Error", {}, None)
        with mock.patch("relay.verify_release._fetch_json", side_effect=err):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "HTTP 500" in capsys.readouterr().out

    def test_tag_name_mismatch_fails(self, healthy_mocks, capsys):
        bad = dict(RELEASE_JSON, tag_name="v9.9.9")
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(bad)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "tag_name" in capsys.readouterr().out

    def test_release_without_assets_lists_everything_missing(self, healthy_mocks, capsys):
        bare = {"tag_name": f"v{VER}", "name": f"v{VER}"}
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(bare)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        out = capsys.readouterr().out
        assert "missing" in out.lower()
        assert WHEEL in out

    def test_junk_asset_entries_are_ignored(self, healthy_mocks, capsys):
        crowded = dict(RELEASE_JSON)
        crowded["assets"] = [
            {"foo": 1},
            {"name": ""},
            *RELEASE_JSON["assets"],
        ]
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                _formula_api_payload() if "homebrew-Relay" in url else dict(crowded)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 0
        assert "all good" in capsys.readouterr().out

    def test_garbage_sums_fails(self, healthy_mocks, capsys):
        with mock.patch("relay.verify_release._fetch_text", return_value="garbage\n"):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "SHA256SUMS" in capsys.readouterr().out

    def test_sums_fetch_error_fails(self, healthy_mocks, capsys):
        with mock.patch(
            "relay.verify_release._fetch_text",
            side_effect=OSError("connection reset"),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "SHA256SUMS" in capsys.readouterr().out

    def test_sums_missing_sdist_entry_fails(self, healthy_mocks, capsys):
        partial = f"{WHEEL_HASH}  {WHEEL}\n"
        with mock.patch("relay.verify_release._fetch_text", return_value=partial):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert SDIST in capsys.readouterr().out

    def test_missing_scoop_file_fails_but_brew_still_checked(self, healthy_mocks, tmp_path, capsys):
        code = run_verify_release(VER, scoop_path=tmp_path / "does-not-exist.json")
        assert code == 1
        out = capsys.readouterr().out
        assert "Scoop manifest" in out
        assert "not found" in out
        assert "Homebrew formula" in out

    def test_unreadable_scoop_file_fails(self, healthy_mocks, tmp_path, capsys):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert run_verify_release(VER, scoop_path=broken) == 1
        out = capsys.readouterr().out
        assert "Scoop manifest" in out
        assert "unreadable" in out

    def test_scoop_url_mismatch_fails(self, healthy_mocks, tmp_path, capsys):
        manifest = {
            "version": VER,
            "url": "https://example.com/some-other-file.whl",
            "hash": f"sha256:{WHEEL_HASH}",
        }
        other = tmp_path / "other.json"
        other.write_text(json.dumps(manifest), encoding="utf-8")
        assert run_verify_release(VER, scoop_path=other) == 1
        assert "url is not the" in capsys.readouterr().out

    def test_brew_payload_error_fails(self, healthy_mocks, capsys):
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                {"content": "eA==", "encoding": "utf-8"}
                if "homebrew-Relay" in url
                else dict(RELEASE_JSON)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "Homebrew formula" in capsys.readouterr().out

    def test_brew_fetch_error_fails(self, healthy_mocks, capsys):
        def fetch(url, timeout=30):
            if "homebrew-Relay" in url:
                raise OSError("connection reset")
            return dict(RELEASE_JSON)

        with mock.patch("relay.verify_release._fetch_json", side_effect=fetch):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "cannot fetch it" in capsys.readouterr().out

    def test_brew_url_mismatch_fails(self, healthy_mocks, capsys):
        doctored = FORMULA_TEXT.replace(SDIST, "other-9.9.9.tar.gz")
        payload = {
            "content": base64.b64encode(doctored.encode()).decode("ascii"),
            "encoding": "base64",
        }
        with mock.patch(
            "relay.verify_release._fetch_json",
            side_effect=lambda url, timeout=30: (
                payload if "homebrew-Relay" in url else dict(RELEASE_JSON)
            ),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks) == 1
        assert "url is not the" in capsys.readouterr().out

    def test_download_error_fails(self, healthy_mocks, capsys):
        with mock.patch(
            "relay.verify_release._fetch_bytes",
            side_effect=OSError("connection reset"),
        ):
            assert run_verify_release(VER, scoop_path=healthy_mocks, download=True) == 1
        assert "cannot download" in capsys.readouterr().out

    def test_download_hash_mismatch_fails(self, tmp_path, capsys):
        import hashlib

        other_digest = hashlib.sha256(b"other-bytes").hexdigest()
        sums = f"{other_digest}  {WHEEL}\n{SDIST_HASH}  {SDIST}\n"
        scoop = _write_scoop_manifest(tmp_path / "relay.json", wheel_hash=other_digest)
        with (
            mock.patch(
                "relay.verify_release._fetch_json",
                side_effect=lambda url, timeout=30: (
                    _formula_api_payload() if "homebrew-Relay" in url else dict(RELEASE_JSON)
                ),
            ),
            mock.patch("relay.verify_release._fetch_text", return_value=sums),
            mock.patch("relay.verify_release._fetch_bytes", return_value=b"wheel-bytes"),
        ):
            assert run_verify_release(VER, scoop_path=scoop, download=True) == 1
        assert "does not match" in capsys.readouterr().out

    def test_verbose_prints_requests(self, healthy_mocks, capsys):
        assert run_verify_release(VER, scoop_path=healthy_mocks, verbose=True) == 0
        assert "[relay] GET" in capsys.readouterr().out


class TestCliRouting:
    def test_parser_accepts_version_and_flags(self):
        args = build_parser().parse_args(["verify-release", "v2.5.0", "--json", "--download"])
        assert args.command == "verify-release"
        assert args.version == "v2.5.0"
        assert args.json_output is True
        assert args.download is True

    def test_parser_version_defaults_to_none(self):
        args = build_parser().parse_args(["verify-release"])
        assert args.version is None

    def test_main_routes_verify_release(self, healthy_mocks, tmp_path, monkeypatch):
        # The CLI resolves the default Scoop manifest from the repo root; point
        # it at the healthy tmp manifest instead (no network, no repo writes).
        import relay.verify_release as vr

        monkeypatch.setattr(vr, "_default_scoop_path", lambda: healthy_mocks)
        with (
            mock.patch(
                "relay.verify_release._fetch_json",
                side_effect=lambda url, timeout=30: (
                    _formula_api_payload() if "homebrew-Relay" in url else dict(RELEASE_JSON)
                ),
            ),
            mock.patch("relay.verify_release._fetch_text", return_value=SHA256SUMS_TEXT),
        ):
            assert main(["verify-release", VER]) == 0
