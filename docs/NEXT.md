# Handoff — malam 09 Aug 2026

Dokumen ini berisi posisi sekarang + rencana lanjutan buat sesi berikutnya.
Baca dulu di awal sesi, terus jalanin sesuai urutan.

## Status sekarang

**v0.4.0 SHIPPED dan live.**

- GitHub Release `v0.4.0` terbit, kedua asset diverifikasi (hash dari API):
  - `relay_cli-0.4.0-py3-none-any.whl` (skitar 60 KB, sha256 `843bc015fd8c56b...`)
  - `relay_cli-0.4.0.tar.gz` (skitar 80 KB, sha256 `2ce6ac4685...`)
- `main` = `6513a08`, ter-push ke `origin`. Tag `v0.4.0` ter-push, release.yml
  sukses (job `build & publish v0.4.0` ✔).
- `Formula/relay.rb` + `bucket/relay.json` sudah di-update ke asset v0.4.0
  (URL + sha256 baru, commit `6513a08`, sudah ter-push).
- **478 test pass** (`python -m pytest -q`).

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

1. **Homebrew untuk v0.4.0 — sudah diuji di Kali Linux, 2 temuan sudah difix:**

   Kelakuan yang terverifikasi (WSL2 Kali, Homebrew 6.0.15):
   - `brew tap Fiqqar/relay https://github.com/Fiqqar/Relay` → tap formula Relay
     (1 formula, 0.4.0); `brew install Fiqqar/relay/relay` → sukses, `relay --version`
     → 0.4.0, `relay doctor` jalan, `brew test` (assert `relay 0.4.0`) → pass.
   - **Homebrew ≥ 6 menolak `brew install <raw-url>`** (berlaku umum, bukan
     khusus Relay: diuji juga dgn formula homebrew-core). Cara tap-by-URL
     itu yang diganti di README + komentar `Formula/relay.rb`.
   - **`relay man` di v0.4.0 memancarkan karakter U+000C** (form feed) karena
     `\fI`/`\fR`/`\fB` di f-string `relay/man.py` ter-escape sebagai Python.
     Sudah difix: man.py sekarang raw f-string (`fr"""`). **Regresi nyata pada
     v0.4.0** — pertimbangkan patch release (v0.4.1) dengan tes tambahan untuk
     pengecekan form feed di output man.
   - Scoop (Windows) belum diuji ulang untuk v0.4.0: `scoop update relay`, atau
     `scoop bucket add relay https://github.com/Fiqqar/Relay` + `scoop
     install relay/relay`.

2. **Scoop bucket `extras` belum di-submit** — opsional, publikasi lebih luas:
   submit PR manifest `relay.json` ke `ScoopInstaller/Extras` supaya
   `scoop install extras/relay` jalan tanpa definisi bucket. Homebrew tap butuh
   repo terpisah bernama `homebrew-Relay`.

3. **`GEMINI_API_KEY` / token dipakai dari env mesin ini** — di mesin lain
   `relay doctor` bakal WARN. Bukan bug.

## Command cek-cek buat pembuka sesi

```powershell
git fetch; git status -sb          # pastikan sync
python -m pytest -q                # harus 478 pass
relay --version                    # harus relay 0.4.0
relay doctor                       # pass (provider & forge token sesuai env)
relay --help                       # cek subcommand: doctor pr undo squash stage telemetry completions man
```

## Saran lanjutan sesi berikutnya (urutkan sendiri)

Prioritas 1 (kuat): **uji ulang instalasi Homebrew (Linux/WSL) & Scoop
(Windows)** untuk v0.4.0 (poin 1). Fix kalau ada error, commit terpisah.

Prioritas 2 (opsional, roadmap "Later"):
- Team default-branch safety rules
- Scoop bucket `extras` + Homebrew tap publikasi
- Provider tambahan lain (Mistral, Groq, dll.) — tinggal tambah class di `relay/ai/` + daftarkan di `_PROVIDERS`
- `relay pr` untuk forge lain (Bitbucket) — pola sudah jelas: buat client baru + routing di `pr.py`