# Dokumentasi Continuous Integration (GitHub Actions) — Kelompok A4

Dokumen ini menjelaskan arsitektur, alur pemeriksaan, serta batasan pipeline **GitHub Actions CI** yang didefinisikan pada [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

---

## 1. Tujuan CI

Pipeline CI berfungsi sebagai *automated quality gate* sebelum perubahan di-merge ke `main`, guna memastikan:
- Seluruh workspace `client/` dan `server/` lolos instalasi bersih, pemeriksaan tipe, linting, build produksi, dan unit tests.
- Konfigurasi container (`compose.yaml` dan `compose.dev.yaml`), build image, konektivitas antar-service, isolasi port/jaringan, serta mount volume tetap valid pada setiap perubahan.

---

## 2. Trigger Workflow

Workflow `CI` berjalan otomatis tanpa filter `paths` atau `paths-ignore` pada:
- **`pull_request` ke `main`:** Wajib lulus sebelum PR di-merge.
- **`push` ke `main`:** Memverifikasi integritas integrasi setelah merge ke `main`.
- **`workflow_dispatch`:** Trigger manual melalui tab **Actions** bila pemeriksaan ulang diperlukan.

Pengaturan `concurrency` membatalkan run lama pada branch PR yang sama ketika commit baru di-push, namun tidak membatalkan run pada branch `main`.

---

## 3. Job dan Pemeriksaan yang Dijalankan

Pipeline terdiri dari dua job berurutan pada runner `ubuntu-latest` dengan `permissions: contents: read` dan `timeout-minutes` terukur:

### Job 1: `Quality Gate` (`quality-gate`)
- Memakai Node.js `22.x` (`engines.node >=22.0.0`) dengan npm cache berbasis `package-lock.json`.
- Menjalankan dari root repository:
  1. `npm ci` (clean install sesuai lockfile, bukan `npm install`)
  2. `npm run typecheck`
  3. `npm run lint`
  4. `npm run build`
  5. `npm test`

### Job 2: `Docker Compose Integration` (`docker-compose-integration`)
Berjalan setelah `Quality Gate` lulus:
1. **Environment Sementara:** Membuat file env sementara di `${{ runner.temp }}/sbs-ci.env` dengan permission `600` dan password acak (`openssl rand -hex 32`) yang di-mask (`::add-mask::`).
2. **Validasi Konfigurasi:** Memeriksa `compose.yaml` maupun gabungan `compose.yaml` + `compose.dev.yaml` menggunakan `docker compose ... config --quiet`.
3. **Full Stack Build & Startup:** Menjalankan `compose.yaml` saja (`build` + `up -d`) dengan project name unik `sbs-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` lalu polling status hingga `db`, `api`, dan `web` ketiganya berstatus `running` (`healthy`).
4. **Endpoint & PostgreSQL Smoke Test:**
   - `GET /` melalui `web` (`127.0.0.1:18080`) mengembalikan HTML starter aplikasi.
   - `GET /healthz` mengembalikan `ok`.
   - `GET /api/v1/health` mengembalikan HTTP `200`, `success: true`, `data.status: "ok"`, `data.service: "sbs-api"`.
   - `pg_isready` dan `psql -Atc "SELECT 1;"` pada container `db` memastikan PostgreSQL 16 merespons query SQL secara nyata.
5. **Verifikasi Isolasi Port, Jaringan & Volume:** Memastikan `db` dan `api` tidak memiliki port host publik, `web` hanya di-bind ke `127.0.0.1`, network `internal` memiliki `Internal=true`, `sbs_pgdata` terpasang di `db`, dan `sbs_uploads` hanya terpasang di `api` (tidak di `web`).
6. **Cleanup Aman:** Langkah `if: always()` menghentikan stack via `docker compose ... down --remove-orphans` (tanpa `-v` dan tanpa `docker volume prune`) serta menghapus file env sementara.

---

## 4. Cara Membaca Hasil & Menelusuri Kegagalan

- **Pada Pull Request:** Buka bagian **Checks** di bawah deskripsi PR (atau tab **Checks** pada halaman PR) untuk melihat status **`Quality Gate`** dan **`Docker Compose Integration`**.
- **Pada Tab Actions:** Pilih workflow **`CI`**, klik run yang sesuai dengan commit atau PR Anda, lalu pilih job dan step yang gagal.
- **Tips Troubleshooting:**
  - Kegagalan pada `npm ci` umumnya disebabkan `package.json` diubah tanpa memperbarui `package-lock.json` di root repository.
  - Kegagalan pada `typecheck` atau `lint` menandakan kesalahan TypeScript atau aturan ESLint di `client/` atau `server/`; reproduksi secara lokal dengan `npm run typecheck && npm run lint`.
  - Kegagalan pada `Docker Compose Integration` dapat diperiksa melalui output langkah **`Collect safe diagnostics on failure`** yang menampilkan `docker compose ps` dan tail log `web`/`api` tanpa mencetak credential.

---

## 5. Perbedaan CI dan CD

Pipeline ini adalah **Continuous Integration (CI)**, **bukan Continuous Deployment (CD)**:
- CI tidak melakukan login ke container registry, tidak mem-publish image Docker, tidak mengakses server produksi, dan tidak mengubah domain/Cloudflare Tunnel/reverse proxy produksi.
- Deployment ke lingkungan server produksi tetap merupakan tanggung jawab terpisah pada `SBS-14`.

---

## 6. Batas CI Sebelum `SBS-19` & Tindak Lanjut Setelah `SBS-19`

- Pada baseline `SBS-20`, endpoint `GET /api/v1/health` memverifikasi respons API dan konektivitas PostgreSQL diuji langsung ke container `db` (`pg_isready` dan `SELECT 1`), **bukan** melalui Prisma Client karena schema Prisma belum dibuat.
- Setelah **`SBS-19`** (Prisma schema, migration, seed, dan database integrity tests) selesai di-merge ke `main`, pipeline CI dapat diperluas dengan langkah validasi schema (`prisma validate`), penerapan migration uji (`prisma migrate deploy`), seed sintetis, dan automated database integration tests pada database CI sementara.
