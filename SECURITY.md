# Security Policy

## Reporting a Vulnerability

If you believe you've found a security vulnerability in Relay, please do not
open a public issue. Report it privately using one of these channels:

- **[GitHub Security Advisory](https://github.com/Fiqqar/Relay/security/advisories/new)** (preferred)
- Email the maintainer: **fiqarsilmy@gmail.com**

Please include:

- A description of the vulnerability and the affected version(s).
- Steps to reproduce it, with the smallest possible example.
- Your suggested fix, if you have one.

Maintainers aim to acknowledge reports within 48 hours and to ship a fix as
soon as we can confirm the issue. We will credit researchers who report valid
vulnerabilities unless they ask not to be named.

## What counts as a vulnerability

Vulnerabilities include — but are not limited to:

- Shell injection through any input relayed to `git` or another subprocess.
- Disclosure of secrets (`GEMINI_API_KEY`, `GITHUB_TOKEN`, `GH_TOKEN`,
  `GITLAB_TOKEN`) via logs, telemetry payloads, or prompts.
- Exfiltration of the diff, commit messages, or filenames to anything other
  than the explicitly configured AI provider.
- Tampering with git history or working trees beyond the documented operations.

## Security design (summary)

Relay is built around a few hard security properties. Contributions must not
weaken them:

- **Secrets are environment-only.** API keys are read from the environment and
  never written to disk, config files, or logs.
- **No shell injection surface.** Every subprocess call passes arguments as a
  list; `shell=True` is never used.
- **Telemetry is opt-in and off by default.** It ships no code or payloads
  until `relay telemetry on` is run *and* `RELAY_TELEMETRY_URL` is set.
- **No data leaves the machine** except requests to the AI provider or forge
  you explicitly configure.

See the [Installation & Security](README.md#security) section of the README
for the full design notes.

## Supported versions

Security fixes are applied to the latest release and, where practical, the
previous release. Older releases are not patched.

| Version | Supported |
| --- | --- |
| latest (v0.7.x) | ✅ |
| previous minor (v0.6.x) | ⚠️ critical fixes only |
| older | ❌ |

## Verification

For maximum supply-chain confidence, verify published artifact checksums —
`sha256` hashes are listed on each [GitHub Release](https://github.com/Fiqqar/Relay/releases)
and pinned in the Scoop manifest.