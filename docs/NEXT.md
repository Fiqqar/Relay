# Handoff — malam 08 Aug 2026

Dokumen ini berisi posisi sekarang + rencana lanjutan buat sesi berikutnya.
Baca dulu di awal sesi, terus jalanin sesuai urutan.

## Status sekarang

**v0.3.0 sudah SHIPPED dan live.**

- GitHub Release `v0.3.0` terbit dengan 2 asset (`relay_cli-0.3.0-py3-none-any.whl` + `.tar.gz`), hash diverifikasi.
- `main` = `2380d36`, sudah ter-push ke `origin`.
- 370 test pass. Build sdist+wheel sukses.
- Packaging:
  - Homebrew formula: `Formula/relay.rb` (belum pernah diuji — butuh macOS/Linux).
  - Scoop manifest: `bucket/relay.json` — **sudah diuji end-to-end di Windows** (`scoop install` → `relay --version` → `relay 0.3.0`, `relay doctor` 7 pass).
- Scoop 0.5.3 terinstall di mesin ini (`~/scoop`), app `relay` aktif dari manifest lokal.

## Yang BELUM beres / bau-bau (prioritas)

1. **Homebrew formula belum pernah diuji.** Wajib ditest di macOS atau Linux (bisa WSL/Ubuntu). Command:
   ```bash
   brew install https://raw.githubusercontent.com/Fiqqar/Relay/main/Formula/relay.rb
   relay --version
   relay doctor
   ```
   Kalau error (biasanya: formula URL harus langsung di-install, atau butuh `python3` formula), fix lalu commit terpisah.

2. **Scoop bucket beneran** ✅ **sudah diverifikasi malam ini**: karena repo punya `bucket/relay.json`, tinggal
   ```bash
   scoop bucket add relay https://github.com/Fiqqar/Relay
   scoop install relay/relay
   ```
   (di mesin ini menghasilkan "already installed" karena `relay` memang sudah terpasang — di mesin fresh akan terinstall. Untuk publikasi lebih luas: submit PR manifest `relay.json` ke bucket `extras` (ScoopInstaller/Extras) supaya `scoop install extras/relay` jalan tanpa definisi bucket. Homebrew tap butuh repo terpisah bernama `homebrew-Relay`.)

3. **Release workflow belum diverifikasi full-matrix** — `.github/workflows/release.yml` sudah pernah jalan (asset ada), tapi check CI matrix hijau di tab Actions untuk tag `v0.3.0` sebelum klaim "cross-platform verified". Buka GitHub → Actions → lihat run terakhir tag `v0.3.0`.

4. **`GEMINI_API_KEY` dipakai dari env mesin ini** — kalau besok bukan di mesin ini, `relay doctor` bakal WARN. Bukan bug.

## Saran lanjutan sesi berikutnya (urutkan sendiri)

Prioritas 1 (kuat): **uji Homebrew di Linux/WSL** (butuh setup WSL kalau belum ada) → fix formula kalau ada error.

Prioritas 2: **v1.0 scope** (kalau mau masuk fitur baru):
- Telemetry opt-in
- Man pages (`man relay`)
- Shell completions (bash/zsh/fish/powershell)

Prioritas 3 (nice-to-have dari roadmap "Later"):
- Multi-commit squashing
- `git add -p`-style partial staging
- Provider tambahan (OpenAI, Anthropic, llama.cpp)
- GitLab PR creation

## Command cek-cek buat pembuka sesi

```powershell
git fetch; git status -sb          # pastikan sync
python -m pytest -q                # 370 harus pass
relay --version                    # harus relay 0.3.0
relay doctor                       # 7 pass, 1 warn (GITHUB_TOKEN optional)
```

Kalau lanjut ke v0.4: bump versi `pyproject.toml` → `git tag v0.4.0` → push → release.yml jalan otomatis (ini pola release yang sama seperti v0.3.0).
