# AGENTS.md — untuk AI / agen yang bekerja di repo ini

> Baca ini dulu, setiap kali memulai sesi kerja baru di repo ini.

## Wajib baca

Sebelum mengubah kode apa pun, baca **`docs/WORKING_RULES.md`** sampai habis dan
ikuti aturannya. Aturan tersebut mengikat manusia maupun AI, dan diulang secara
ringkas di sini:

- **Satu logical change = satu commit** (Conventional Commits:
  `type(scope): subject`). Jangan mencampur tugas beda topik dalam satu commit.
- **Jangan pernah commit/push sebelum** `pytest` (coverage ≥ 85%), `ruff check .`,
  dan `mypy relay` semuanya hijau. Test baru wajib satu commit dengan kodenya.
- **Zero runtime dependency** — stdlib only.
- **`pyproject.toml`** dev deps harus tetap single-line array (test memparsingnya
  dengan parser TOML internal yang tidak mendukung multi-line).
- **Semua subprocess argv-as-list; `shell=True` dilarang.** Secrets env-only.
- **Jangan reformat massal** (jangan `ruff format` seluruh repo), jangan merapikan
  kode yang tidak berhubungan dengan tugas.
- Kerjakan task satu per satu dan buat commit terpisah per task sesuai instruksi.

## Info repo

- Python 3.10+, entry point `relay.cli:main`, package `relay` + `relay.ai`.
- Git identity: `Fiqqar` / `fiqarsilmy@gmail.com`.
- Remote: `https://github.com/Fiqqar/Relay.git`. Branch default: `main`.
- Rilis: runbook di `RELEASE.md` (bump versi, re-point Formula/Scoop dengan hash
  asli dari `python -m build` lokal, tag `v*` memicu release CI).
