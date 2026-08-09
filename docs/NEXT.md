# Handoff — malam 09 Aug 2026

Dokumen ini berisi posisi sekarang + rencana lanjutan buat sesi berikutnya.
Baca dulu di awal sesi, terus jalanin sesuai urutan.

## Status sekarang

**v0.4.1 SHIPPED dan live — Scoop & Homebrew sudah terverifikasi.**

- GitHub Release `v0.4.1` terbit (patch release setelah Kali Linux),
  kedua asset diverifikasi:
  - `relay_cli-0.4.1-py3-none-any.whl` (61 KB, sha256 `76dd919d1ef4481...`)
  - `relay_cli-0.4.1.tar.gz` (80 KB, sha256 `381d484c973cc8e5...`)
- `main` = `b06b8cb`, ter-push ke `origin`. Tag `v0.4.1` ter-push, release.yml
  sukses.
- `Formula/relay.rb` + `bucket/relay.json` sudah di-update ke asset v0.4.1
  (URL + sha256 baru) dan **terverifikasi instalasinya**:
  - Scoop (Windows): `scoop update relay` 0.3.0→0.4.1, hash cocok,
    `relay doctor` → 7 pass, `relay man` → 0 form feed.
  - Homebrew (Kali/WSL2, Homebrew 6.0.15): tap `Fiqqar/relay`, `brew upgrade`
    0.4.0→0.4.1, `brew test` pass.
- **479 test pass** (`python -m pytest -q`) — termasuk regresi test untuk
  form-feed di output `relay man`.

### Isi v0.4.1 (patch)

Temuan dari uji Homebrew di Kali Linux (WSL2, Homebrew 6.0.15):
- **`relay man` memancarkan karakter U+000C (form feed)** di v0.4.0 karena
  `\fI`/`\fR`/`\fB` di f-string `relay/man.py` ter-escape sebagai Python.
  Difix jadi raw f-string (`fr"""`) + tes regresi. Terverifikasi: `relay man`
  → 0 form feed, troff escape (`\fI`, `\-\-`) utuh.
- **Homebrew ≥ 6 menolak `brew install <raw-url>`**. README + komentar
  `Formula/relay.rb` diganti ke cara tap-by-URL.
- Install path yang benar di Homebrew:
  `brew tap Fiqqar/relay https://github.com/Fiqqar/Relay` +
  `brew install Fiqqar/relay/relay`.

Fitur yang masuk v0.4.0 (semua di-commit per fitur):
- Shell completions (bash/zsh/fish/powershell) + `relay man` page
- Usage telemetry opt-in (default off)
- `relay squash` — fold N commit terakhir jadi satu (never push)
- `relay stage` — partial staging: pilih file / hunk (`git add -p`)
- Provider tambahan: OpenAI, Anthropic, + OpenAI-compatible (llama.cpp/vLLM via `OPENAI_BASE_URL`)
- `relay pr` — dukungan GitLab MR (gitlab.com + self-hosted, `GITLAB_TOKEN`)

`relay doctor` sekarang ngecek 4 provider (gemini|ollama|openai|anthropic) +
forge token (GITHUB / GITLAB).

## Yang BELUM beres / bau-bau (prioritas)

1. **Scoop bucket `extras` belum di-submit** — opsional, publikasi lebih luas:
   submit PR manifest `relay.json` ke `ScoopInstaller/Extras` supaya
   `scoop install extras/relay` jalan tanpa definisi bucket. Homebrew tap butuh
   repo terpisah bernama `homebrew-Relay`.

2. **`GEMINI_API_KEY` / token dipakai dari env mesin ini** — di mesin lain
   `relay doctor` bakal WARN. Bukan bug.

## Command cek-cek buat pembuka sesi

```powershell
git fetch; git status -sb          # pastikan sync
python -m pytest -q                # harus 479 pass
relay --version                    # harus relay 0.4.1
relay doctor                       # pass (provider & forge token sesuai env)
relay --help                       # cek subcommand: doctor pr undo squash stage telemetry completions man
```

## Saran lanjutan sesi berikutnya (urutkan sendiri)

Prioritas 1 (kuat): **Scoop (Windows) & Homebrew (Kali) untuk v0.4.1 sudah
PASS** — tidak ada fix yang tersisa. Lanjut ke fitur berikutnya.

Prioritas 2 (opsional, roadmap "Later"):
- Team default-branch safety rules
- Scoop bucket `extras` + Homebrew tap publikasi
- Provider tambahan lain (Mistral, Groq, dll.) — tinggal tambah class di `relay/ai/` + daftarkan di `_PROVIDERS`
- `relay pr` untuk forge lain (Bitbucket) — pola sudah jelas: buat client baru + routing di `pr.py`