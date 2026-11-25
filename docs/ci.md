# Dokumentasi Continuous Integration (GitHub Actions) — Kelompok A4

Dokumen ini menjelaskan arsitektur, alur pemeriksaan, serta batasan pipeline **GitHub Actions Continuous Integration (CI)** pada [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

---

## 1. Tujuan CI

Pipeline CI menjadi *automated quality gate* sebelum perubahan di-merge ke branch `main`. Setiap Pull Request dan push ke `main` diperiksa secara konsisten untuk memastikan:
- Workspace `client/` dan `server/` lulus instalasi bersih, typecheck, lint, build produksi, dan unit tests.
- Konfigurasi Docker Compose (`compose.yaml` dan `compose.dev.yaml`), build image, health service, konektivitas dasar PostgreSQL, isolasi port/jaringan, serta mount volume tetap valid.

---

## 2. Trigger Workflow dan Ruleset

Workflow `CI` berjalan otomatis tanpa filter `paths` maupun `paths-ignore` pada event berikut:
- **`pull_request` (`main`):** Memeriksa setiap Pull Request menuju `main`.
- **`push` (`main`):** Memverifikasi integritas integrasi setelah merge ke `main`.
- **`workflow_dispatch`:** Trigger manual melalui tab **Actions** bila pemeriksaan ulang diperlukan.

Pengaturan `concurrency` membatalkan workflow run lama pada branch PR yang sama ketika commit baru di-push, sementara run pada branch `main` tetap dijalankan sampai selesai. Pengaktifan kembali Ruleset `Main Rule` serta pendaftaran required status checks (`Quality Gate` dan `Docker Compose Integration`) dilakukan manual oleh Project Owner setelah PR CI di-merge.

---

## 3. Job dan Pemeriksaan

Workflow berjalan pada GitHub-hosted runner `ubuntu-latest` dengan permission baseline `contents: read`, pinning full commit SHA pada action resmi (`actions/checkout` dan `actions/setup-node`), serta batas `timeout-minutes` pada tiap job.

### Job 1: `Quality Gate` (`quality-gate`)
- Menggunakan Node.js `22.x` (selaras dengan `engines.node >=22.0.0` dan Dockerfile) beserta npm cache dari `package-lock.json`.
- Menjalankan perintah berikut dari root repository:
  1. `npm ci`
  2. `npm run typecheck`
  3. `npm run lint`
  4. `npm run build`
  5. `npm test`

### Job 2: `Docker Compose Integration` (`docker-compose-integration`)
Berjalan setelah `Quality Gate` lulus:
1. **Environment sementara:** Membuat `$RUNNER_TEMP/sbs-ci.env` (`chmod 600`) dengan password acak `openssl rand -hex 32` yang di-mask memakai `::add-mask::`.
2. **Validasi konfigurasi:** Memeriksa `compose.yaml` dan gabungan `compose.yaml` + `compose.dev.yaml` melalui `docker compose ... config --quiet`.
3. **Build dan startup full stack:** Menjalankan `compose.yaml` (`build` dan `up -d`) dengan project terisolasi `sbs-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}`, lalu melakukan polling status hingga `db`, `api`, dan `web` berstatus `running` (`healthy`).
4. **Smoke test endpoint dan PostgreSQL:**
   - `GET /` melalui `web` (`127.0.0.1:18080`) mengembalikan HTML starter aplikasi.
   - `GET /healthz` mengembalikan `ok`.
   - `GET /api/v1/health` mengembalikan HTTP `200`, `success: true`, `data.status: "ok"`, dan `data.service: "sbs-api"`.
   - `pg_isready` dan `psql -Atc "SELECT 1;"` pada container `db` memastikan PostgreSQL 16 menerima koneksi dan mengeksekusi query SQL.
5. **Verifikasi isolasi port, jaringan, dan volume:** Memastikan `db` dan `api` tidak memiliki port host publik, `web` hanya di-bind ke `127.0.0.1`, network `internal` memiliki `Internal=true`, `sbs_pgdata` terpasang pada `db`, serta `sbs_uploads` hanya terpasang pada `api` (tidak pada `web`).
6. **Cleanup aman:** Langkah `if: always()` menghentikan stack dengan `docker compose ... down --remove-orphans` (tanpa `-v` dan tanpa `docker volume prune`) serta menghapus file environment sementara.

---

## 4. Membaca Hasil Workflow dan Menelusuri Kegagalan

- **Pada Pull Request:** Buka bagian **Checks** pada halaman Pull Request untuk memeriksa status **`Quality Gate`** dan **`Docker Compose Integration`**.
- **Pada tab Actions:** Pilih workflow **`CI`**, buka workflow run sesuai commit atau PR terkait, lalu periksa step yang gagal.
- **Troubleshooting umum:**
  - Kegagalan `npm ci`: pastikan `package-lock.json` di root repository sudah disinkronkan bila ada perubahan `package.json`.
  - Kegagalan `typecheck` atau `lint`: reproduksi secara lokal dari root dengan `npm run typecheck && npm run lint`.
  - Kegagalan `Docker Compose Integration`: periksa output langkah **`Collect safe diagnostics on failure`** yang menampilkan `docker compose ps` dan tail log `web`/`api` tanpa mencetak credential.

---

## 5. Perbedaan CI dan CD

Workflow ini hanya menjalankan **Continuous Integration (CI)**, bukan **Continuous Deployment (CD)**:
- CI tidak melakukan login ke container registry, tidak mem-publish Docker image, tidak mengakses server produksi, dan tidak mengubah domain, Nginx server, maupun Cloudflare Tunnel.
- Proses deployment ke server produksi tetap berada pada scope `SBS-14`.

---

## 6. Batas CI Sebelum `SBS-19` dan Rencana Lanjutan

- Pada baseline saat ini, `GET /api/v1/health` memeriksa kesiapan proses Express API, dan pengujian database CI menguji container `db` melalui `pg_isready` serta `SELECT 1`. Pengujian schema Prisma belum dijalankan karena schema belum tersedia sebelum `SBS-19` selesai.
- Setelah **`SBS-19`** (Prisma schema, migration, seed sintetis, dan database integrity tests) di-merge ke `main`, pipeline CI dapat diperluas untuk menjalankan `prisma validate`, `prisma migrate deploy`, seed sintetis, dan automated database integration tests terhadap database CI sementara.
