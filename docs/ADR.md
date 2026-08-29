# Relay — Architecture Decision Records (ADR)

> Kenapa Relay dibangun seperti ini. Setiap ADR: Context → Decision → Consequences.
> Nomor tetap, jangan dihapus — kalau keputusan berubah, tambah ADR baru yang supersede.

---

## ADR-001 — Pure-stdlib, zero runtime dependencies

**Context:** CLI global harus install di mana saja, termasuk mesin offline / lab SMK tanpa internet stabil. Depedency berat (`requests`, `typer`, `pydantic`) menambah supply-chain risk dan break offline.

**Decision:** Hanya stdlib: `argparse`, `subprocess`, `urllib`, `tomllib`/`relay/toml.py`, `unittest.mock` untuk test. `pyproject.toml:dependencies = []`.

**Consequences:** + Install selalu berhasil, audit surface kecil. − Harus tulis parser TOML mini & HTTP manual; tidak bisa pakai fitur fancy framework.

## ADR-002 — Git via subprocess (argv-as-list) bukan library

**Context:** Alternatif: `GitPython` / `dulwich`. Mereka reimplement credential helper & hook handling.

**Decision:** `subprocess.run(["git", ...], shell=False)` — reuse credential helper, SSH agent, dan hooks user apa adanya. Semua argumen sebagai list; `shell=True` forbidden (enforced di `WORKING_RULES.md`).

**Consequences:** + Kompatibel dengan setup git apapun; anti shell-injection. − Harus handle `FileNotFoundError` jika git tidak di PATH (`relay/doctor.py`, `relay/git_manager.py`).

## ADR-003 — AI behind `AIManager` interface + provider registry

**Context:** Butuh Gemini default, Ollama lokal, plus OpenAI-compatible. Tidak mau `if provider ==` tersebar.

**Decision:** `relay/ai/base.py` abstract `generate_commit_message(diff, stat, branch) -> str` + `build_prompt`. Registry `_PROVIDERS` di `relay/ai/__init__.py`. Provider baru = subclass `OpenAIProvider` + register + test + doctor branch. Lihat `CONTRIBUTING.md#adding-an-ai-provider`.

**Consequences:** + Tambah provider tanpa ubah orchestrator. − Harus jaga kontrak error `AIError(kind, provider)` konsisten.

## ADR-004 — Manual fallback, never block workflow

**Context:** FR-7: AI down/rate-limited/offline tidak boleh abort. Banyak tool AI fail-hard — buruk untuk low-connectivity.

**Decision:** Setiap `AIError` / invalid Conventional Commit → `FALLBACK` → `input()` manual (subject + optional body, blank line finish). Lazy provider build: missing API key → `provider=None` → fallback, bukan `ConfigError` hard fail. Non-TTY → exit 1 tanpa hang.

**Consequences:** + Workflow selalu lanjut. − Pesan manual tidak divalidasi (verbatim commit).

## ADR-005 — Precedence: flags > env > config file > defaults; secrets env-only

**Context:** Config file nyaman, tapi secrets di file = bocor kalau repo di-share. `RELAY_CONFIG` bisa diarahkan ke repo untrusted.

**Decision:** `relay/config.py:_resolve` — env menang atas file. Secrets (`*_API_KEY`, `*_TOKEN`) + AI base URLs + GitLab trusted hosts **env-only**; file di-ignore untuk key tersebut. Config file cache per `(path, mtime, size)`.

**Consequences:** + File bisa di-share tanpa takut leak; repo jahat tidak bisa redirect token. − User harus set env untuk secrets (dokumentasikan di `relay doctor`).

## ADR-006 — Protected-branch guard default-deny

**Context:** Team mode `relay --team` sering dijalankan dari `main` — risiko commit langsung ke default branch.

**Decision:** `RELAY_PROTECTED_BRANCHES` / `[team.protected] branches` default `["main","master"]` (case-insensitive). Team mode menolak jika `current_branch` protected; hanya `--allow-protected` yang bypass. `--yes` tidak bypass (decoupled di v0.5.1). Solo mode tetap boleh commit anywhere (konvensi).

**Consequences:** + Mencegah kesalahan paling mahal (push ke main). − Butuh escape hatch eksplisit untuk repo yang memang commit ke main.

## ADR-007 — Diff truncation: line cap + byte budget

**Context:** Diff besar bisa exceed token window LLM atau OOM. Line cap saja gagal untuk single line sangat panjang.

**Decision:** `RELAY_MAX_DIFF_LINES` (default 120) + hard byte budget 512 KiB (`relay/orchestrator.py`). Truncation report ke user. `max_diff_lines` tolerant parsing (bool/list → default).

**Consequences:** + Prompt selalu muat; tidak ada OOM dari diff. − Pesan AI mungkin kurang konteks jika diff terpotong (user bisa raise limit).

## ADR-008 — Dry-run via `git diff HEAD`, TOCTOU guard via `write-tree`

**Context:** `--dry-run` seharusnya tidak mutasi index. Race antara AI call dan `git add .` bisa commit state berbeda.

**Decision:** Dry-run tidak `git add .`; pakai `git diff HEAD` untuk preview. Guard: `git write-tree` sebelum AI, verifikasi index unchanged sebelum `git commit`. Lihat `docs/FLOW.md`.

**Consequences:** + Dry-run benar-benar side-effect free; race terdeteksi. − Satu subprocess ekstra per run.

## ADR-009 — Forge routing with trusted-host allowlist

**Context:** `relay pr` derive host dari `origin` remote — data yang bisa dikontrol repo jahat. Token bisa exfiltrated ke host attacker.

**Decision:** `github.com` / `bitbucket.org` hard-trusted; `gitlab.com` default trusted + `RELAY_TRUSTED_GITLAB_HOSTS` env-only allowlist (additive, tidak replace). Untrusted host → refuse sebelum baca token/kirim request. `https` only; `http` hanya untuk `localhost` (Ollama). Validasi URL scheme sebelum `webbrowser.open`.

**Consequences:** + Token tidak pernah ke host attacker. − Self-hosted GitLab butuh env var eksplisit.

## ADR-010 — Single-line `dev` array in `pyproject.toml`

**Context:** `relay/toml.py` subset parser tidak support multi-line arrays. CI tidak pakai `tomllib` di 3.10.

**Decision:** Keep `dev = ["pytest>=8", ...]` single-line. Rule di `WORKING_RULES.md` + `tests/test_version.py` / `test_toml.py` guard.

**Consequences:** + Parser sederhana tetap work. − Formatting `pyproject.toml` tidak bisa auto-wrap array.

## ADR-011 — One logical change = one commit; dogfooding via `relay` itself

**Context:** Clean history adalah guiding star. AI/agent sering bundle banyak fix jadi satu commit.

**Decision:** `WORKING_RULES.md` + `AGENTS.md` require satu commit per logical change + commit & push via `relay --solo/--team --yes` (split & push straight). `ruff format` whole-repo forbidden.

**Consequences:** + History bisectable, reviewable. − Butuh disiplin (tapi `relay` sendiri yang enforce).

---

## Superseded / Future

- Jika butuh multi-provider failover, buat ADR-012 (saat ini out of scope).
- Jika butuh TUI, buat ADR baru yang justify deps — jangan diam-diam tambah deps.
