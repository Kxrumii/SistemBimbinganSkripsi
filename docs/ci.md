# Dokumentasi Continuous Integration (GitHub Actions) — Kelompok A4

Dokumen ini menjelaskan arsitektur, alur pemeriksaan, serta batasan pipeline **GitHub Actions Continuous Integration (CI)** pada [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

---

## 1. Tujuan CI

Pipeline CI menjadi *automated quality gate* sebelum perubahan di-merge ke branch `main`. Setiap Pull Request dan push ke `main` diperiksa secara konsisten untuk memastikan:
- Workspace `client/` dan `server/` lulus instalasi bersih, typecheck, lint, build produksi, dan unit tests.
- Service PostgreSQL 16 (`db`) pada Mode A (`compose.yaml` + `compose.dev.yaml`) dapat dijalankan terisolasi pada `127.0.0.1:5432`, siap menerima koneksi dari host runner, dan menjalankan gate database kondisional untuk schema, migration, seed, serta database integrity tests (`SBS-19`).
- Konfigurasi Docker Compose full stack (`compose.yaml`), build image, health service, konektivitas dasar PostgreSQL, isolasi port/jaringan, serta mount volume tetap valid.

---

## 2. Trigger Workflow dan Ruleset

Workflow `CI` berjalan otomatis tanpa filter `paths` maupun `paths-ignore` pada event berikut:
- **`pull_request` (`main`):** Memeriksa setiap Pull Request menuju `main`.
- **`push` (`main`):** Memverifikasi integritas integrasi setelah merge ke `main`.
- **`workflow_dispatch`:** Trigger manual melalui tab **Actions** bila pemeriksaan ulang diperlukan.

Pengaturan `concurrency` membatalkan workflow run lama pada branch PR yang sama ketika commit baru di-push, sementara run pada branch `main` tetap dijalankan sampai selesai. Pengaktifan kembali Ruleset `Main Rule` serta pendaftaran required status checks (**`Quality Gate`**, **`Database Integration`**, dan **`Docker Compose Integration`**) dilakukan manual oleh Project Owner setelah PR CI di-merge.

---

## 3. Job dan Pemeriksaan

Workflow berjalan pada GitHub-hosted runner `ubuntu-latest` dengan permission baseline `contents: read`, pinning full commit SHA pada action resmi (`actions/checkout` dan `actions/setup-node`), serta batas `timeout-minutes` pada tiap job. Setelah `Quality Gate` lulus, **`Database Integration`** dan **`Docker Compose Integration`** berjalan paralel dengan project Docker Compose yang terisolasi satu sama lain.

### Job 1: `Quality Gate` (`quality-gate`)
- Menggunakan Node.js `22.x` (selaras dengan `engines.node >=22.0.0` dan Dockerfile) beserta npm cache dari `package-lock.json`.
- Menjalankan perintah berikut dari root repository:
  1. `npm ci`
  2. `npm run typecheck`
  3. `npm run lint`
  4. `npm run build`
  5. `npm test`

### Job 2: `Database Integration` (`database-integration`)
Berjalan setelah `Quality Gate` lulus (paralel dengan `Docker Compose Integration`):
1. **Checkout penuh (`fetch-depth: 0`):** Menyertakan history commit agar SHA base branch Pull Request (`github.event.pull_request.base.sha`) tersedia untuk deteksi anti-bypass penghapusan schema.
2. **Setup Node.js `22.x` dan `npm ci`:** Memasang dependency workspace `client/` dan `server/` secara bersih sebelum menjalankan script database.
3. **Environment sementara:** Membuat `$RUNNER_TEMP/sbs-db-ci.env` (`chmod 600`) dengan password acak `openssl rand -hex 32` yang di-mask, serta mengeksport `DATABASE_URL` (`postgresql://sbs_ci_user:<password>@127.0.0.1:5432/sbs_ci?schema=public`) ke `GITHUB_ENV` dalam kondisi ter-mask (`::add-mask::`).
4. **Startup PostgreSQL terisolasi (Mode A):** Memvalidasi `compose.yaml` + `compose.dev.yaml`, menjalankan **hanya** service `db` dengan project terisolasi `sbs-db-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}`, lalu menunggu hingga `db` berstatus `running` (`healthy`).
5. **Verifikasi port binding dan konektivitas host runner:** Memastikan `db` hanya mempublikasikan `127.0.0.1:5432`, menerima koneksi TCP dari host runner, serta lulus `pg_isready` dan query `SELECT 1` pada `127.0.0.1:5432`.
6. **Gate kondisional Prisma & anti-bypass penghapusan schema:**
   - **Sebelum `SBS-19` (`server/prisma/schema.prisma` belum ada pada base `main` maupun PR):** Langkah PostgreSQL readiness dan `SELECT 1` tetap berjalan dan wajib lulus, sedangkan pemeriksaan Prisma dicatat secara eksplisit sebagai tidak berlaku (`N/A`) dan job berakhir sukses.
   - **Proteksi anti-bypass:** Pada event `pull_request`, jika `server/prisma/schema.prisma` sudah ada pada base branch `main` tetapi tidak ditemukan pada head PR, job langsung gagal untuk mencegah penghapusan schema demi melewati pemeriksaan database.
   - **Setelah `SBS-19` (`server/prisma/schema.prisma` tersedia):** Job memvalidasi kelengkapan artefak kontrak (`server/prisma/schema.prisma`, minimal satu `server/prisma/migrations/**/migration.sql`, `server/prisma/seed.ts`, dan script non-placeholder pada `server/package.json`), lalu menjalankan secara berurutan:
     1. `npm run db:validate --workspace=server`
     2. `npm run db:migrate:deploy --workspace=server`
     3. `npm run db:seed --workspace=server`
     4. `npm run test:db --workspace=server`
7. **Cleanup aman:** Langkah `if: always()` menghentikan service dengan `docker compose ... down --remove-orphans` (tanpa `-v` dan tanpa `docker volume prune`) serta menghapus file environment sementara.

### Job 3: `Docker Compose Integration` (`docker-compose-integration`)
Berjalan setelah `Quality Gate` lulus (paralel dengan `Database Integration`):
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

## 4. Kontrak Integrasi Database (`SBS-19`)

Agar `Database Integration` otomatis mengaktifkan seluruh pemeriksaan Prisma saat **`SBS-19`** (dan seluruh PR berikutnya setelah `SBS-19` di-merge) berjalan, repository mewajibkan artefak berikut pada workspace `server/`:
- **File wajib:**
  - `server/prisma/schema.prisma`
  - Minimal satu file migrasi `server/prisma/migrations/<nama_migrasi>/migration.sql`
  - `server/prisma/seed.ts`
- **Script wajib pada `server/package.json` (harus berupa perintah nyata, bukan placeholder seperti `echo` atau `exit 0`):**
  - `db:validate` (validasi schema Prisma)
  - `db:migrate:deploy` (menerapkan migrasi ke database kosong menggunakan `DATABASE_URL`)
  - `db:seed` (mengisi data awal sintetis yang aman untuk CI)
  - `test:db` (menjalankan automated database integration dan integrity tests)

---

## 5. Membaca Hasil Workflow dan Menelusuri Kegagalan

- **Pada Pull Request:** Buka bagian **Checks** pada halaman Pull Request untuk memeriksa status **`Quality Gate`**, **`Database Integration`**, dan **`Docker Compose Integration`**.
- **Pada tab Actions:** Pilih workflow **`CI`**, buka workflow run sesuai commit atau PR terkait, lalu periksa step yang gagal.
- **Troubleshooting umum:**
  - Kegagalan `npm ci`: pastikan `package-lock.json` di root repository sudah disinkronkan bila ada perubahan `package.json`.
  - Kegagalan `typecheck` atau `lint`: reproduksi secara lokal dari root dengan `npm run typecheck && npm run lint`.
  - Kegagalan `Database Integration` (penghapusan schema / artefak kurang): pastikan `server/prisma/schema.prisma`, `server/prisma/migrations/**/migration.sql`, `server/prisma/seed.ts`, serta seluruh script `db:validate`, `db:migrate:deploy`, `db:seed`, dan `test:db` tersedia lengkap dan tidak memakai perintah placeholder.
  - Kegagalan `db:migrate:deploy`, `db:seed`, atau `test:db`: jalankan `npm run dev:db:up` secara lokal (Mode A pada `127.0.0.1:5432`), periksa kesesuaian `DATABASE_URL`, lalu reproduksi perintah `npm run <script> --workspace=server` yang gagal.
  - Kegagalan `Docker Compose Integration`: periksa output langkah **`Collect safe diagnostics on failure`** yang menampilkan `docker compose ps` dan tail log `web`/`api` tanpa mencetak credential.

---

## 6. Perbedaan CI dan CD

Workflow ini hanya menjalankan **Continuous Integration (CI)**, bukan **Continuous Deployment (CD)**:
- CI tidak melakukan login ke container registry, tidak mem-publish Docker image, tidak mengakses server produksi, dan tidak mengubah domain, Nginx server, maupun layanan tunnel/proxy eksternal.
- Proses deployment ke server produksi tetap berada pada scope `SBS-14`.

---

## 7. Batas Baseline Sebelum `SBS-19`

- Sebelum `SBS-19` di-merge ke `main`, `GET /api/v1/health` memeriksa kesiapan proses Express API, dan `Database Integration` menguji kesiapan PostgreSQL Mode A dari host runner (`127.0.0.1:5432`, `pg_isready`, `SELECT 1`), sementara tahap Prisma (`db:validate`, `db:migrate:deploy`, `db:seed`, `test:db`) otomatis berstatus tidak berlaku (`N/A`).
- Begitu `SBS-19` menambahkan `server/prisma/schema.prisma` dan artefak kontraknya, job `Database Integration` otomatis mengeksekusi seluruh rangkaian validasi schema, migrasi, seed sintetis, dan uji integritas database pada setiap PR berikutnya.
