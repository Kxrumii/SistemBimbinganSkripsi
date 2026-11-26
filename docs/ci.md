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
1. **Checkout penuh (`fetch-depth: 0`):** Menyertakan history commit agar base commit untuk pemeriksaan immutability tersedia (*fail-closed*: `github.event.pull_request.base.sha` untuk `pull_request`, `github.event.before` untuk `push`, dan fallback `HEAD^` untuk `workflow_dispatch`; kegagalan resolusi base commit langsung menggagalkan job).
2. **Setup Node.js `22.x` dan `npm ci`:** Memasang dependency workspace `client/` dan `server/` secara bersih sebelum menjalankan self-test dan script database.
3. **Self-test validator kontrak CI:** Menjalankan `python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v` untuk memverifikasi helper `.github/scripts/validate_db_contract.py` (skenario positif maupun negatif untuk canonical schema path, penolakan wrapper `npx`/`npm exec`, resolusi base commit *fail-closed*, isi migration SQL, `migration_lock.toml`, immutability, exact executable + environment allowlist, shell chaining, direktori database test, TAP summary, dan Step Summary) bahkan sebelum `SBS-19` tersedia. *(Self-test ini memeriksa validator CI dan bukan pengganti test database aplikasi.)*
4. **Environment sementara:** Membuat `$RUNNER_TEMP/sbs-db-ci.env` (`chmod 600`) dengan password acak `openssl rand -hex 32` yang di-mask, serta mengekspor `DATABASE_URL` (`postgresql://sbs_ci_user:<password>@127.0.0.1:5432/sbs_ci?schema=public`) ke `GITHUB_ENV` dalam kondisi ter-mask (`::add-mask::`).
5. **Startup PostgreSQL terisolasi (Mode A):** Memvalidasi `compose.yaml` + `compose.dev.yaml`, menjalankan **hanya** service `db` dengan project terisolasi `sbs-db-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}`, lalu menunggu hingga `db` berstatus `running` (`healthy`).
6. **Verifikasi port binding dan konektivitas host runner:** Memastikan `db` hanya mempublikasikan `127.0.0.1:5432`, menerima koneksi TCP dari host runner, serta lulus `pg_isready` dan query `SELECT 1` pada `127.0.0.1:5432`.
7. **Deteksi schema, validasi kontrak kanonis, dan gate kondisional Prisma:**
   - **Sebelum `SBS-19` (`server/prisma/schema.prisma` belum ada pada base maupun PR):** Self-test validator, PostgreSQL readiness, dan `SELECT 1` tetap berjalan dan wajib lulus, sedangkan pemeriksaan kontrak aplikasi `SBS-19` dan eksekusi Prisma dicatat secara eksplisit sebagai tidak berlaku (`N/A`) hingga `SBS-19` menambahkan schema Prisma.
   - **Proteksi anti-bypass penghapusan schema:** Pada `pull_request`, `push`, dan `workflow_dispatch`, jika `server/prisma/schema.prisma` sudah ada di base commit tetapi hilang pada head, job langsung gagal dan tidak turun ke mode `N/A`.
   - **Validasi lokasi kanonis, isi, & immutability migrasi (saat schema tersedia):** `.github/scripts/validate_db_contract.py` mewajibkan `server/prisma/schema.prisma`, `server/prisma/migrations/migration_lock.toml` dengan `provider = "postgresql"`, setiap `<migrasi>/migration.sql` tidak kosong dan memuat SQL executable setelah komentar `--` dan `/* ... */` dibuang, serta seluruh `migration.sql` pada commit base tetap identik (*fail-closed* terhadap kegagalan `git rev-parse` / `git ls-tree`). Opsi `--schema` hanya boleh dihilangkan atau tepat `prisma/schema.prisma`; path schema alternatif, `--config`, file `prisma.config.*`, serta key pengalih path pada `package.json#prisma` ditolak.
   - **Validasi direct local executable, exact token, & allowlist environment:** Setiap script database (`db:validate`, `db:migrate:deploy`, `db:seed`, `test:db`) pada `server/package.json` wajib memanggil direct local executable yang terpasang di `node_modules/.bin` melalui `npm run --workspace=server`. Wrapper `npx` dan `npm exec`, executable/path separator `/` atau `\`, assignment environment generik (`PATH=`, `NODE_PATH=`, `NODE_OPTIONS=`, `HOME=`, `IFS=`, dll.), operator shell chaining/redirection (`;`, `||`, `|`, `&&`, `&`, `>`, `<`, `$()`, backtick), serta flag tak dikenal ditolak. Hanya `NODE_ENV=test` (maksimal satu kali) yang diizinkan khusus pada `test:db`. Aturan exact token matching ini berfungsi sebagai penjagaan kontrak script dan bukan sandbox OS. Direktori khusus `server/src/__tests__/database/*.test.ts` wajib tersedia dengan minimal satu file test non-empty berisi deklarasi `test(`/`it(` yang dapat dijalankan.
   - **Eksekusi aplikasi & validasi output TAP:** Menjalankan `db:validate`, `db:migrate:deploy`, dan `db:seed` via `--workspace=server`, menjalankan `npm run test:db --workspace=server | tee "$RUNNER_TEMP/sbs-db-tests.tap"`, lalu menjalankan `validate_db_contract.py verify-tap` untuk memastikan ringkasan TAP melaporkan `# tests > 0`, `# pass > 0`, `# fail == 0`, `# cancelled == 0`, dan tidak seluruh test dilewati (`# skipped < # tests`).
   - **Batas validasi otomatis `test:db`:** Meskipun `test:db` dijalankan terhadap PostgreSQL CI yang hidup dan ringkasan TAP diverifikasi, validator CI tidak membuktikan secara statis bahwa seluruh isi test benar-benar melakukan query ke PostgreSQL atau Prisma. Reviewer pada `SBS-19` dan PR database berikutnya tetap wajib memeriksa bahwa pengujian benar-benar menguji database nyata, bukan mock-only atau assertion statis.
8. **Cleanup aman & GitHub Step Summary (`if: always()`):** Menghapus file TAP sementara dan menghentikan service dengan `docker compose ... down --remove-orphans` (tanpa `-v` dan tanpa `docker volume prune`) serta menghapus file environment sementara, lalu menulis tabel lima baris **`Database Integration Coverage`** ke `$GITHUB_STEP_SUMMARY` berdasarkan outcome aktual (memisahkan **PostgreSQL infrastructure**, **CI validator self-tests**, **SBS-19 schema/script/migration contract**, **Prisma application integration**, dan **Overall Database Integration**).

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
  - `server/prisma/schema.prisma` (non-empty)
  - `server/prisma/migrations/migration_lock.toml` (`provider = "postgresql"`)
  - Minimal satu file migrasi `server/prisma/migrations/<nama_migrasi>/migration.sql` yang non-empty dan berisi statement SQL valid (bukan komentar atau `;` saja)
  - `server/prisma/seed.ts` (non-empty)
  - Minimal satu file test database pada `server/src/__tests__/database/*.test.ts` yang non-empty dan memiliki deklarasi `test(...)` atau `it(...)` yang dapat dijalankan
- **Script wajib pada `server/package.json` (satu direct local executable tanpa wrapper `npx`/`npm exec`, tanpa path `/` atau `\`, tanpa `--config`, dengan `--schema` dihilangkan atau tepat `prisma/schema.prisma`, tanpa `;`, `||`, `|`, `&&`, `&`, redirection, `$()`, backtick, maupun env generik; hanya `NODE_ENV=test` yang diizinkan khusus pada `test:db`):**
  - `db:validate`: `prisma validate` (atau dengan `--schema=prisma/schema.prisma`)
  - `db:migrate:deploy`: `prisma migrate deploy` (menggunakan `DATABASE_URL`; tanpa `--schema` alternatif)
  - `db:seed`: `prisma db seed`, `tsx prisma/seed.ts`, atau `node --import tsx prisma/seed.ts` *(apabila `server/package.json` memiliki blok `"prisma"`, hanya `"schema": "prisma/schema.prisma"` dan `"seed"` direct runner yang diizinkan; `prisma.config.*` ditolak)*
  - `test:db`: menjalankan suite khusus `src/__tests__/database/` memakai test runner Node.js/tsx dengan format TAP, misalnya:
    - `node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts` *(disarankan)*
    - `tsx --test --test-reporter=tap src/__tests__/database/*.test.ts` *(ekuivalen yang juga diterima)*

---

## 5. Membaca Hasil Workflow dan Menelusuri Kegagalan

- **Pada Pull Request:** Buka bagian **Checks** pada halaman Pull Request untuk memeriksa status **`Quality Gate`**, **`Database Integration`**, dan **`Docker Compose Integration`**.
- **Pada tab Actions:** Pilih workflow **`CI`**, buka workflow run sesuai commit atau PR terkait, lalu periksa step yang gagal.
- **Troubleshooting umum:**
  - Kegagalan `npm ci`: pastikan `package-lock.json` di root repository sudah disinkronkan bila ada perubahan `package.json`.
  - Kegagalan `typecheck` atau `lint`: reproduksi secara lokal dari root dengan `npm run typecheck && npm run lint`.
  - Kegagalan `Database Integration` (validasi kontrak / immutability):
    - Jika gagal karena penghapusan `server/prisma/schema.prisma` atau modifikasi/penghapusan migrasi lama, kembalikan file dari base branch dan buat direktori migrasi baru jika ada perubahan schema.
    - Jika gagal karena migrasi kosong, `migration_lock.toml` salah, `src/__tests__/database/` kosong, atau script dianggap placeholder, perbaiki sesuai Bagian 4 lalu uji lokal dengan `python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v`.
  - Kegagalan `db:migrate:deploy`, `db:seed`, `test:db`, atau `verify-tap`: jalankan `npm run dev:db:up` secara lokal (Mode A pada `127.0.0.1:5432`), periksa `DATABASE_URL`, lalu jalankan `npm run db:migrate:deploy --workspace=server`, `npm run db:seed --workspace=server`, dan `npm run test:db --workspace=server` untuk memastikan minimal satu test berjalan dan lulus.
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
