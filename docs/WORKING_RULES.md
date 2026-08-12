# Working Rules (Wajib Baca)

> **MUST-READ.** Dokumen ini wajib dibaca sampai habis **sebelum mulai mengerjakan
> apa pun** di repo ini — oleh manusia, maupun oleh AI/agen yang bekerja atas nama
> manusia. Kalau kamu AI, mulai setiap sesi kerja dengan membaca file ini terlebih
> dahulu (dan `CONTRIBUTING.md` untuk proses rilis). Melanggar aturan di sini = PR
> ditolak / kerjaan diulang.

## Prinsip inti

Relay adalah CLI kecil yang bangga dengan **zero runtime dependency** dan **Git
history yang bersih**. Dua hal itu adalah kompas utama. Setiap keputusan teknis
harus melindungi keduanya.

## Aturan wajib

### 1. Commit — Conventional Commits, satu change satu commit

- Format: `type(scope): subject`, contoh `fix(squash): refuse dirty index`.
- Type yang valid: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`,
  `perf`, `build`, `ci`, `revert`.
- **Satu logical change = satu commit.** Kalau subjeknya butuh kata "and", pecah.
- Jangan mencampur fix + docs + refactor dalam satu commit.
- Subjek imperatif ("add", bukan "added"), di bawah ~72 karakter.

### 2. Jangan pernah push langsung tanpa verifikasi

Sebelum push, jalankan berturut-turut dan pastikan semuanya PASS:

```bash
python -m pytest -q --cov=relay --cov-branch --cov-fail-under=85
ruff check .
mypy relay
```

- Coverage gate 85% (branch) wajib tembus.
- Unit test untuk perilaku baru **harus masuk di commit yang sama** dengan kodenya.
- Test harus hermetic: tidak boleh bergantung pada network, `$HOME`, provider AI
  asli, atau env var yang tidak di-set di CI.

### 3. Zero runtime dependency — absolut

- Hanya stdlib. Tidak menambah dependency runtime tanpa alasan yang sangat kuat
  (dan harus didiskusikan dulu).
- Dev dependencies hidup di satu baris array di `pyproject.toml` — **jangan
  dipisah jadi multi-line**, karena `tests/test_version.py` memparsing
  `pyproject.toml` dengan parser TOML internal Relay yang tidak mendukung
  multi-line array. Melanggar ini = test gagal.

### 4. Keamanan & integritas Git

- **Semua subprocess lewat argv-as-list, `shell=True` TIDAK PERNAH boleh.**
- Secrets (API keys, tokens) **hanya dari env var** — tidak pernah ditulis ke
  file, tidak pernah di-commit, tidak pernah di-log.
- Jangan tambahkan operasi git yang destruktif (`reset --hard`, `checkout -- .`,
  force-push otomatis) ke dalam alur. Alur Relay menjamin "no destructive git".

### 5. Jangan reformat massal

- Jangan jalankan `ruff format` (atau formatter lain) ke seluruh repo — ini akan
  me-reformat puluhan file dan membuat noise di history. Lint cukup `ruff check .`.

### 6. Kalau kamu AI, aturan khusus

- Baca file ini di **setiap awal sesi kerja** sebelum menyentuh file apa pun.
- Jangan kerjakan beberapa tugas dalam satu commit — buat commit terpisah per
  perbaikan/fitur, sesuai konvensi di atas.
- Jangan "rapikan" kode yang tidak berhubungan dengan tugas lo. Kalau kamu lihat
  bug lain, catat dan lapor — jangan diam-diam di-fix dalam commit yang beda topik.
- Jangan pernah mengedit file tanpa membaca dulu konteks sekitarnya.
- Kalau perintah tidak jelas atau berdampak besar, tanya dulu — jangan menebak.

### 7. Verifikasi akhir sebelum menyerahkan hasil

- Jalankan semua check di aturan #2.
- Kalau menyentuh alur solo fallback, jalankan juga e2e:
  `bash e2e_test.sh` (macOS/Linux) atau `powershell -ExecutionPolicy Bypass -File e2e_test.ps1` (Windows).
- Lapor dengan ringkas: apa yang diubah, kenapa, dan hasil verifikasi.

## Hal yang sering salah (checklist)

- [ ] Subjek commit > 72 karakter / bukan imperatif
- [ ] Satu commit berisi banyak perubahan tak berkaitan
- [ ] Test baru tidak disertakan di commit yang sama
- [ ] `pyproject.toml` diubah jadi multi-line array
- [ ] Menambahkan dependency runtime tanpa diskusi
- [ ] Memformat ulang file yang tidak disentuh tugas
- [ ] Push sebelum test/lint/mypy hijau
