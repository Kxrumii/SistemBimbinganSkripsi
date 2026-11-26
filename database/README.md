# Database Foundation (`database/`)

Direktori ini disiapkan sebagai lokasi dokumentasi rancangan ERD dan artefak pendukung basis data (`SBS-03` dan `SBS-19`).

## Kontrak Service PostgreSQL (dari `SBS-04`)

- **Engine:** PostgreSQL 16 (`postgres:16-alpine`).
- **Isolasi Mode Full Stack (`compose.yaml`):**
  - Berjalan hanya pada jaringan `internal` (`internal: true`), **tanpa publikasi port ke host**.
  - Service `api` terhubung melalui hostname internal **`db:5432`**.
- **Akses Mode Development Lokal (`compose.dev.yaml`):**
  - Override `compose.dev.yaml` menambahkan port binding khusus loopback **`127.0.0.1:5432:5432`** agar backend atau tools migrasi di host lokal dapat terhubung melalui `127.0.0.1:5432`.
  - Dijalankan dengan project terpisah `sbs-dev` melalui `npm run dev:db:up` dan dihentikan melalui `npm run dev:db:down` (tanpa menghapus volume).
- **Named Volume:** `sbs_pgdata` terpasang pada `/var/lib/postgresql/data`.
- **Variabel & Kredensial:** `POSTGRES_DB`, `POSTGRES_USER` (`[a-z0-9_]+`), `POSTGRES_PASSWORD` (hex URL-safe dari `openssl rand -hex 32`), dan `DATABASE_URL` yang memakai password identik.
- **Tanggung Jawab `SBS-19`:** Implementasi `server/prisma/schema.prisma`, migration PostgreSQL, seed data sintetis, dan pengujian integritas database dikerjakan pada **SBS-19**.

## Kontrak Integrasi GitHub Actions CI (`Database Integration`)

Job `Database Integration` pada [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) menyediakan instance PostgreSQL 16 Mode A (`compose.yaml` + `compose.dev.yaml`) pada `127.0.0.1:5432` dengan `DATABASE_URL` sementara pada setiap Pull Request dan push ke `main`. Sebelum `server/prisma/schema.prisma` tersedia (`SBS-19` belum di-merge), CI menjalankan self-test validator kontrak dan memverifikasi kesiapan PostgreSQL (`PASS`), sementara Step Summary melaporkan `SBS-19 schema/script/migration contract` serta `Prisma application integration` sebagai `N/A`.

Saat **`SBS-19`** (serta Pull Request setelahnya) menambahkan schema Prisma, repository wajib menyediakan kontrak berikut pada workspace `server/`:
- **Lokasi kanonis & larangan pengalihan konfigurasi:**
  - `server/prisma/schema.prisma` (non-empty); opsi `--schema` pada script hanya boleh dihilangkan atau tepat `prisma/schema.prisma`. Path alternatif, `--config`, file `prisma.config.*`, maupun key `package.json#prisma` yang mengalihkan `schema`/`migrations` di luar `server/prisma/` ditolak.
  - `server/prisma/migrations/migration_lock.toml` dengan `provider = "postgresql"`
  - Minimal satu `server/prisma/migrations/<nama_migrasi>/migration.sql` yang valid, non-empty, dan berisi SQL executable (bukan komentar atau `;` saja)
  - `server/prisma/seed.ts` (non-empty)
  - Direktori test khusus database `server/src/__tests__/database/*.test.ts` berisi minimal satu file test non-empty yang benar-benar dapat dijalankan
- **Script wajib pada `server/package.json` (harus satu direct local executable *fail-closed* dari dependency workspace tanpa wrapper `npx`/`npm exec`, tanpa path `/` atau `\`, tanpa env prefix seperti `PATH=`/`NODE_PATH=`/`NODE_OPTIONS=`/`HOME=`/`IFS=`, dan tanpa `;`, `||`, `|`, `&&`, `&`, redirection, `$()`, backtick, placeholder, maupun unit test generik; hanya `NODE_ENV=test` yang diizinkan khusus pada `test:db`):**
  1. `db:validate` — menjalankan `prisma validate`
  2. `db:migrate:deploy` — menjalankan `prisma migrate deploy`
  3. `db:seed` — menjalankan seed sintetis (`prisma db seed`, `tsx prisma/seed.ts`, atau `node --import tsx prisma/seed.ts`)
  4. `test:db` — menjalankan database test directory memakai runner test bawaan dengan output TAP, misalnya:
     `node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts`
- **Ketentuan immutability & batas verifikasi test:**
  - Migration SQL yang sudah ada pada base branch (`main`) bersifat immutable (tidak boleh dihapus, diubah, atau diganti nama pada Pull Request berikutnya), dan kegagalan resolusi base commit atau `git ls-tree` akan langsung menggagalkan CI (*fail-closed*). Penambahan migrasi baru dilakukan melalui direktori migrasi baru.
  - Setelah `server/prisma/schema.prisma` tersedia di `main`, Pull Request yang menghapus file tersebut otomatis digagalkan.
  - Output TAP dari `test:db` diperiksa oleh CI untuk memastikan minimal satu test berjalan dan lulus (`# tests > 0`, `# pass > 0`, `# fail == 0`, serta tidak seluruh test berstatus skip). Karena CI tidak memverifikasi isi AST setiap test apakah benar-benar memanggil Prisma/PostgreSQL, reviewer pada `SBS-19` wajib meninjau bahwa test menjalankan operasi database nyata, bukan mock-only atau assertion statis. Detail lengkap dijelaskan pada [`docs/ci.md`](../docs/ci.md).
