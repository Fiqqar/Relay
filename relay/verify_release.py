"""relay verify-release — end-to-end verification of a published release.

Checks that a published Relay release is internally consistent and that both
package channels track it: the ``vx.y.z`` tag exists with the strict title,
the sdist + wheel assets match ``SHA256SUMS``, and the Scoop manifest plus
the Homebrew formula point at the same version and hashes.

Pure stdlib only, matching the zero-dependency philosophy of the rest of the
tool. Read-only: verifies, never mutates. Every failure degrades to a FAIL
row — this command never tracebacks.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .errors import RelayError, sanitize_terminal
from .github import github_token

_RELEASE_TAG_URL = (
    "https://api.github.com/repos/Fiqqar/Relay/releases/tags/{tag}"
)
_FORMULA_CONTENTS_URL = (
    "https://api.github.com/repos/Fiqqar/homebrew-Relay/contents/relay.rb"
)

# A release payload is a few KiB; SHA256SUMS is smaller still. The wheel is a
# few hundred KiB — 64 MiB is generous headroom, not an invitation.
_MAX_JSON_BYTES = 1024 * 1024
_MAX_TEXT_BYTES = 1024 * 1024
_MAX_WHEEL_BYTES = 64 * 1024 * 1024
# Asset hosts redirect (GitHub release downloads answer 302 to a CDN). The
# global opener refuses every redirect so a token can never leak to another
# host, so public assets follow redirects explicitly below instead — bounded.
_MAX_REDIRECTS = 5

_MARKS = {"ok": "PASS", "fail": "FAIL", "skip": "SKIP"}

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_URL_RE = re.compile(r'url\s+"([^"]+)"')
_FORMULA_SHA_RE = re.compile(r'sha256\s+"([^"]+)"')


class VerifyError(RelayError):
    """A release verification step failed."""


@dataclass
class Check:
    name: str
    status: str  # ok | fail | skip
    detail: str = ""


def normalize_version(raw: str | None) -> str:
    """Normalize a version argument to bare ``x.y.z`` (no ``v`` prefix).

    ``None`` means the installed Relay version. Raises :class:`VerifyError`
    when the value has no PEP 440 ``x.y.z`` shape.
    """
    value = __version__ if raw is None else raw
    value = value.strip()
    if value[:1].lower() == "v":
        value = value[1:]
    parts = value.split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        raise VerifyError(f"invalid version {raw!r} (expected x.y.z or vx.y.z)")
    return value


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse a ``sha256sum``-style manifest into ``{filename: digest}``."""
    entries: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != 2:
            raise VerifyError(f"SHA256SUMS line {lineno} is malformed")
        digest, name = parts
        name = name.lstrip("*")
        if not _SHA256_RE.fullmatch(digest):
            raise VerifyError(f"SHA256SUMS line {lineno} has a bad digest")
        entries[name] = digest.lower()
    if not entries:
        raise VerifyError("SHA256SUMS is empty")
    return entries


def parse_formula(text: str) -> tuple[str, str]:
    """Extract ``(url, sha256)`` from a Homebrew formula body."""
    url_match = _URL_RE.search(text)
    sha_match = _FORMULA_SHA_RE.search(text)
    if url_match is None or sha_match is None:
        raise VerifyError("Homebrew formula has no url/sha256 stanza")
    sha = sha_match.group(1)
    if not _SHA256_RE.fullmatch(sha):
        raise VerifyError("Homebrew formula has a bad sha256")
    return url_match.group(1), sha.lower()


def _headers(accept: str) -> dict[str, str]:
    headers = {"User-Agent": "relay-cli", "Accept": accept}
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_json(url: str, timeout: int = 30) -> Any:
    """GET a GitHub API URL and decode its JSON body (size-capped)."""
    req = urllib.request.Request(
        url, headers=_headers("application/vnd.github+json")
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        body = resp.read(_MAX_JSON_BYTES + 1)
    if len(body) > _MAX_JSON_BYTES:
        raise VerifyError(f"response from {url} exceeded the size limit")
    return json.loads(body.decode("utf-8", "replace"))


def _fetch_public_body(url: str, timeout: int, max_bytes: int, kind: str) -> bytes:
    """GET a public release asset, following redirects explicitly.

    Asset hosts (and their redirect targets) never receive credentials: every
    hop builds a fresh unauthenticated request, so a token can never leak to
    a redirected host. Redirects are bounded; anything else raises.
    """
    current = url
    for _ in range(_MAX_REDIRECTS):
        req = urllib.request.Request(
            current, headers={"User-Agent": "relay-cli", "Accept": "*/*"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                body = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in (301, 302, 303, 307, 308) and location:
                current = urllib.parse.urljoin(current, location)
                continue
            raise
        if len(body) > max_bytes:
            raise VerifyError(f"{kind} from {url} exceeded the size limit")
        return body
    raise VerifyError(f"too many redirects fetching {kind} from {url}")


def _fetch_text(url: str, timeout: int = 30) -> str:
    """GET a small text asset (SHA256SUMS) with a size cap."""
    return _fetch_public_body(url, timeout, _MAX_TEXT_BYTES, "SHA256SUMS").decode(
        "utf-8", "replace"
    )


def _fetch_bytes(url: str, timeout: int = 30) -> bytes:
    """GET a release artifact for local re-hashing (size-capped)."""
    return _fetch_public_body(url, timeout, _MAX_WHEEL_BYTES, "artifact")


def _default_scoop_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bucket" / "relay.json"


def _decode_formula_payload(payload: Any) -> str:
    """Decode a GitHub contents-API payload into the formula body."""
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise VerifyError("Homebrew formula payload is not base64")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise VerifyError("Homebrew formula payload is empty")
    try:
        return base64.b64decode(content).decode("utf-8", "replace")
    except (binascii.Error, ValueError) as exc:
        raise VerifyError(f"Homebrew formula payload is corrupt ({exc})") from exc


def _report(
    ver: str, tag: str, checks: list[Check], json_output: bool
) -> int:
    failed = sum(1 for c in checks if c.status == "fail")
    passed = sum(1 for c in checks if c.status == "ok")
    skipped = sum(1 for c in checks if c.status == "skip")
    exit_code = 0 if failed == 0 else 1
    if json_output:
        print(
            json.dumps(
                {
                    "version": ver,
                    "tag": tag,
                    "checks": [
                        {
                            "name": sanitize_terminal(c.name),
                            "status": c.status,
                            "detail": sanitize_terminal(c.detail),
                        }
                        for c in checks
                    ],
                    "summary": {
                        "pass": passed,
                        "fail": failed,
                        "skip": skipped,
                    },
                    "exit_code": exit_code,
                },
                indent=2,
            )
        )
        return exit_code
    print(f"[relay verify-release] Relay {ver} ({tag})")
    print()
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        print(
            f"  {sanitize_terminal(c.name):<{width}}"
            f"{_MARKS[c.status]:<7}{sanitize_terminal(c.detail)}"
        )
    verdict = "all good" if failed == 0 else f"{failed} issue(s) need fixing"
    print()
    print(f"  {passed} pass, {failed} fail - {verdict}.")
    return exit_code


def run_verify_release(
    version: str | None = None,
    *,
    json_output: bool = False,
    download: bool = False,
    verbose: bool = False,
    scoop_path: str | Path | None = None,
) -> int:
    """Verify a published release end-to-end. Returns the exit code."""
    try:
        ver = normalize_version(version)
    except VerifyError as exc:
        print(f"[relay verify-release] invalid version: {sanitize_terminal(str(exc))}")
        return 1
    tag = f"v{ver}"
    wheel = f"relay_cli-{ver}-py3-none-any.whl"
    sdist = f"relay_cli-{ver}.tar.gz"
    checks: list[Check] = []

    def note_fetch(url: str) -> None:
        if verbose and not json_output:
            print(f"[relay] GET {sanitize_terminal(url)}")

    # ---- 1. the tag exists with the strict title -------------------------
    tag_url = _RELEASE_TAG_URL.format(tag=tag)
    note_fetch(tag_url)
    try:
        release = _fetch_json(tag_url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            checks.append(Check("Release tag", "fail", f"{tag} not found on GitHub"))
        else:
            checks.append(
                Check("Release tag", "fail", f"GitHub API HTTP {exc.code}")
            )
        return _report(ver, tag, checks, json_output)
    except Exception as exc:  # noqa: BLE001 - verify must never traceback
        checks.append(Check("Release tag", "fail", f"cannot reach GitHub ({exc})"))
        return _report(ver, tag, checks, json_output)
    if not isinstance(release, dict) or release.get("tag_name") != tag:
        found = release.get("tag_name") if isinstance(release, dict) else None
        checks.append(
            Check("Release tag", "fail", f"tag_name is {found!r}, expected {tag!r}")
        )
        return _report(ver, tag, checks, json_output)
    # The API calls the release title `name` (`gh release create --title`
    # maps to it); there is no `title` field.
    name = release.get("name")
    if name != tag:
        checks.append(
            Check(
                "Release tag",
                "fail",
                f"release name is {name!r}, expected {tag!r} "
                "(must be strictly vx.y.z)",
            )
        )
        return _report(ver, tag, checks, json_output)
    checks.append(Check("Release tag", "ok", f"{tag} exists"))

    # ---- 2. the expected assets are attached ------------------------------
    raw_assets = release.get("assets")
    assets: dict[str, str] = {}
    if isinstance(raw_assets, list):
        for entry in raw_assets:
            if isinstance(entry, dict) and entry.get("name"):
                assets[str(entry["name"])] = str(
                    entry.get("browser_download_url") or ""
                )
    missing = [n for n in (wheel, sdist, "SHA256SUMS") if not assets.get(n)]
    if missing:
        checks.append(
            Check("Release assets", "fail", "missing: " + ", ".join(missing))
        )
        return _report(ver, tag, checks, json_output)
    checks.append(
        Check("Release assets", "ok", f"{wheel}, {sdist}, SHA256SUMS present")
    )

    # ---- 3. SHA256SUMS covers the artifacts --------------------------------
    note_fetch(assets["SHA256SUMS"])
    try:
        sums = parse_sha256sums(_fetch_text(assets["SHA256SUMS"]))
    except VerifyError as exc:
        checks.append(Check("SHA256SUMS", "fail", str(exc)))
        return _report(ver, tag, checks, json_output)
    except Exception as exc:  # noqa: BLE001 - verify must never traceback
        checks.append(Check("SHA256SUMS", "fail", f"cannot fetch it ({exc})"))
        return _report(ver, tag, checks, json_output)
    uncovered = [n for n in (wheel, sdist) if n not in sums]
    if uncovered:
        checks.append(
            Check("SHA256SUMS", "fail", "no entry for: " + ", ".join(uncovered))
        )
        return _report(ver, tag, checks, json_output)
    checks.append(Check("SHA256SUMS", "ok", "covers the wheel + sdist"))

    # ---- 4. the Scoop manifest tracks this release -------------------------
    scoop_file = Path(scoop_path) if scoop_path is not None else _default_scoop_path()
    try:
        manifest = json.loads(scoop_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        checks.append(
            Check("Scoop manifest", "fail", f"{scoop_file} not found")
        )
        manifest = None
    except (OSError, ValueError) as exc:
        checks.append(Check("Scoop manifest", "fail", f"unreadable ({exc})"))
        manifest = None
    if manifest is not None:
        if manifest.get("version") != ver:
            checks.append(
                Check(
                    "Scoop manifest",
                    "fail",
                    f"version is {manifest.get('version')!r}, expected {ver!r}",
                )
            )
        elif not str(manifest.get("url") or "").endswith(f"v{ver}/{wheel}"):
            checks.append(
                Check("Scoop manifest", "fail", f"url is not the {tag} wheel")
            )
        elif str(manifest.get("hash") or "").removeprefix("sha256:").lower() != sums[
            wheel
        ]:
            checks.append(
                Check(
                    "Scoop manifest",
                    "fail",
                    "hash does not match the SHA256SUMS wheel entry",
                )
            )
        else:
            checks.append(
                Check("Scoop manifest", "ok", f"version {ver}, hash matches")
            )

    # ---- 5. the Homebrew formula tracks this release ------------------------
    note_fetch(_FORMULA_CONTENTS_URL)
    try:
        formula_body = _decode_formula_payload(_fetch_json(_FORMULA_CONTENTS_URL))
        formula_url, formula_sha = parse_formula(formula_body)
    except VerifyError as exc:
        checks.append(Check("Homebrew formula", "fail", str(exc)))
        formula_url, formula_sha = "", ""
    except Exception as exc:  # noqa: BLE001 - verify must never traceback
        checks.append(
            Check("Homebrew formula", "fail", f"cannot fetch it ({exc})")
        )
        formula_url, formula_sha = "", ""
    else:
        if not formula_url.endswith(f"v{ver}/{sdist}"):
            checks.append(
                Check("Homebrew formula", "fail", f"url is not the {tag} sdist")
            )
        elif formula_sha != sums[sdist]:
            checks.append(
                Check(
                    "Homebrew formula",
                    "fail",
                    "sha256 does not match the SHA256SUMS sdist entry",
                )
            )
        else:
            checks.append(
                Check("Homebrew formula", "ok", f"version {ver}, sha256 matches")
            )

    # ---- 6. optional: re-hash the wheel --------------------------------------
    if download:
        note_fetch(assets[wheel])
        try:
            digest = hashlib.sha256(_fetch_bytes(assets[wheel])).hexdigest()
        except Exception as exc:  # noqa: BLE001 - verify must never traceback
            checks.append(
                Check("Download", "fail", f"cannot download the wheel ({exc})")
            )
        else:
            if digest != sums[wheel]:
                checks.append(
                    Check(
                        "Download",
                        "fail",
                        "downloaded wheel hash does not match SHA256SUMS",
                    )
                )
            else:
                checks.append(
                    Check("Download", "ok", "wheel bytes match SHA256SUMS")
                )

    return _report(ver, tag, checks, json_output)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(run_verify_release(sys.argv[1] if len(sys.argv) > 1 else None))
