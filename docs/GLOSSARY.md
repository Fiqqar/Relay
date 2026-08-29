# Relay — Glossary

> Istilah yang dipakai di docs, kode, dan saat sidang/UKK. Ditulis untuk teman SMK — singkat, contoh nyata.

| Istilah | Arti | Contoh |
|---------|------|--------|
| **Conventional Commits** | Format pesan commit `type(scope): subject` agar history bisa di-parse mesin | `feat(payments): add retry handling` |
| **type** | Kategori perubahan: `feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore`/`perf`/`build`/`ci`/`revert` | `fix(squash): refuse dirty index` |
| **scope** | Area kode yang diubah (opsional) | `feat(ai): add groq provider` |
| **Solo mode** | `relay --solo` — stage → commit → push ke branch sekarang | `relay --solo --yes` |
| **Team mode** | `relay --team <feature>` — buat branch `<type>/<feature>` baru lalu commit & push | `relay --team payments` → `feat/payments` |
| **Preflight** | Cek cepat sebelum mutasi: di dalam git repo? ada perubahan? remote ada? | `git rev-parse --is-inside-work-tree` |
| **Staged / Unstaged** | Staged = sudah `git add`, siap commit. Unstaged = masih di working tree | `relay --staged` hanya commit yang sudah staged |
| **Diff (`git diff --cached`)** | Ringkasan perubahan yang akan dikomit — ini yang dikirim ke LLM | `+ added line` / `- removed line` |
| **`--dry-run`** | Simulasi: tampilkan rencana + pesan, tidak ubah repo sama sekali | `relay --dry-run` |
| **`--yes` / `-y`** | Lewati konfirmasi `Accept/Edit/Retry/Abort` | `relay --solo --yes` |
| **`--no-push`** | Commit saja, jangan push | Dipakai saat mau review dulu sebelum push |
| **`--staged`** | Jangan `git add .`, hanya commit yang sudah staged | Untuk seleksi manual file |
| **`--allow-protected`** | Bypass penjaga branch terproteksi (`main`/`master`) — satu-satunya cara di team mode | `relay --team fix --allow-protected` |
| **Protected branches** | Branch yang team mode tolak secara default (`main`, `master`, bisa di-config) | `RELAY_PROTECTED_BRANCHES=main,develop` |
| **Branch template** | Pola nama branch: default `<type>/<feature>` → `feat/payments` | `RELAY_BRANCH_TEMPLATE=release/<feature>` |
| **Fallback (manual)** | Jika AI gagal (offline/rate-limit/timeout/garbage) → minta input manual, lanjut workflow | `[relay] AI unavailable — continuing with manual input.` |
| **Provider** | Backend LLM: `gemini`/`ollama`/`openai`/`anthropic`/`mistral`/`groq`/`xai` | `--provider ollama` |
| **Base URL** | Endpoint HTTP provider; bisa diarahkan ke server lokal (llama.cpp/vLLM) — env-only | `OPENAI_BASE_URL=http://localhost:8080/v1` |
| **Token budget / truncation** | Batas ukuran diff yang dikirim ke LLM (120 baris + 512 KiB) agar tidak exceed | `RELAY_MAX_DIFF_LINES=250` |
| **Forge** | Platform hosting git: GitHub / GitLab / Bitbucket | `relay pr` buat PR/MR |
| **PR / MR** | Pull Request (GitHub/Bitbucket) / Merge Request (GitLab) — permintaan gabung branch | `relay pr --draft --open` |
| **Trusted hosts (GitLab)** | Daftar host yang boleh menerima `GITLAB_TOKEN`; cegah exfiltrasi via `origin` palsu | `RELAY_TRUSTED_GITLAB_HOSTS=gitlab.company.com` |
| **Dogfooding** | Commit project Relay itu sendiri pakai `relay` — bukan `git commit` | `relay --solo --yes` di repo Relay |
| **Hermetic tests** | Test yang tidak butuh network/`$HOME`/AI real — deterministik di CI | `pytest` mock `urllib.request.urlopen` |
| **Coverage gate 90%** | Minimal 90% branch coverage — push ditolak kalau di bawah | `pytest --cov=relay --cov-branch --cov-fail-under=90` |
| **argv-as-list / `shell=False`** | Jalankan `git` tanpa shell, cegah injection dari nama file/branch | `subprocess.run(["git", "push", "--", branch])` |
| **TOCTOU** | Time-of-check vs time-of-use race; Relay pakai `git write-tree` guard | Cek index sebelum commit |
| **SSRF** | Server-Side Request Forgery — cegah URL jahat redirect token | Validasi `https` + allowlist host |
| **Telemetry (opt-in)** | Laporan anonim `mode/provider/ok` — mati default, perlu `relay telemetry on` + `RELAY_TELEMETRY_URL` | Tidak pernah kirim diff/pesan |
| **TOML config** | File config opsional `[relay]` di `$XDG_CONFIG_HOME/relay/config.toml` | `provider = "ollama"` |
| **Exit codes** | `0` sukses, `1` error workflow, `130` user abort (Ctrl-C) | Dipakai CI & script |
| **NFR** | Non-Functional Requirement — performa, keamanan, portabilitas | NFR-3 secrets env-only |
| **ADR** | Architecture Decision Record — catatan alasan keputusan desain | `docs/ADR.md` |

## Singkatan cepat (buat sidang)

- **PRD** — Product Requirements Document (`docs/SPEC.md`)
- **FR/NFR** — Functional / Non-Functional Requirements
- **UKK** — Uji Kompetensi Keahlian (SMK)
- **LLM** — Large Language Model (AI yang buat pesan commit)
- **CI** — Continuous Integration (GitHub Actions)
