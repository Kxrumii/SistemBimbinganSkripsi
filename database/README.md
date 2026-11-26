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
- **Tanggung Jawab `SBS-19`:** Implementasi Prisma ORM **`7.10.1`** (`prisma` dan `@prisma/client`), canonical `server/prisma7.config.ts`, `server/prisma/schema.prisma`, migration PostgreSQL, seed data sintetis, dan pengujian integritas database dikerjakan pada **SBS-19**.

## Kontrak Integrasi GitHub Actions CI (`Database Integration`)

Job `Database Integration` pada [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) menyediakan instance PostgreSQL 16 Mode A (`compose.yaml` + `compose.dev.yaml`) pada `127.0.0.1:5432` dengan `DATABASE_URL` sementara pada setiap Pull Request dan push ke `main`. Sebelum `SBS-19` dimulai (ketika schema, config Prisma, dependency, maupun script DB belum ada), CI menjalankan self-test validator kontrak dan memverifikasi kesiapan PostgreSQL (`PASS`), sementara Step Summary melaporkan `SBS-19 schema/script/migration contract` serta `Prisma application integration` sebagai `N/A`. Bila artefak parsial `SBS-19` ditambahkan tanpa kontrak lengkap, CI langsung menggagalkan job dan tidak turun ke status `N/A`.

Saat **`SBS-19`** (serta Pull Request setelahnya) mengimplementasikan database layer, repository wajib memenuhi seluruh kontrak berikut pada workspace `server/`:
- **Target versi & lockfile (`7.10.1` stable):**
  - `server/package.json` wajib mematok `devDependencies.prisma = "7.10.1"` dan `dependencies["@prisma/client"] = "7.10.1"` secara eksak (tanpa `^`, `~`, `latest`, Prisma 8 RC, maupun Prisma 6).
  - Root `package-lock.json` wajib mengunci kedua paket ke `7.10.1` (tanpa `server/package-lock.json` terpisah maupun override di root `package.json`), serta `npm ci` tidak boleh mengubah `package-lock.json`.
- **Canonical Prisma configuration (`server/prisma7.config.ts`) & pemuatan root `.env`:**
  - Wajib menyediakan tepat satu file konfigurasi non-symlink pada **`server/prisma7.config.ts`** dengan isi deterministik kanonis yang memuat root `.env` (`../.env` relatif terhadap `import.meta.url`) dengan `override: false` agar `DATABASE_URL` dari environment proses/CI tetap diprioritaskan (dan `server/.env` tidak dipakai):
    ```ts
    import dotenv from "dotenv";
    import path from "node:path";
    import { fileURLToPath } from "node:url";
    import { defineConfig } from "prisma/config";

    const configDirectory = path.dirname(fileURLToPath(import.meta.url));

    dotenv.config({
      path: path.resolve(configDirectory, "../.env"),
      override: false,
    });

    export default defineConfig({
      schema: "prisma/schema.prisma",
      migrations: {
        path: "prisma/migrations",
      },
      datasource: {
        url: process.env["DATABASE_URL"],
      },
    });
    ```
  - Dilarang membuat `.env` di dalam `server/`, menggunakan `import "dotenv/config"`, `process.cwd()`, atau `DOTENV_PATH`, membuat file konfigurasi alternatif atau symlink pada root repository maupun `server/` (`prisma.config.*`, `prisma7.config.*` selain `server/prisma7.config.ts`, `.config/prisma.*`, `.config/prisma7.*`, `.config/prisma.config.*`, maupun variasi `/index.*` untuk ekstensi `.js`, `.ts`, `.mjs`, `.cjs`, `.mts`, `.cts`), schema liar di luar `server/prisma/schema.prisma`, serta blok `"prisma"` pada root `package.json` maupun `server/package.json`. File `.env` lokal tidak pernah di-commit ke Git.
- **Artefak & lokasi kanonis pada `server/`:**
  - `server/prisma/schema.prisma` (non-empty, non-symlink); `db:validate` dan `db:migrate:deploy` wajib menuliskan eksplisit `--schema=prisma/schema.prisma` (atau `--schema prisma/schema.prisma`), tanpa `--config`, duplikasi `--schema`, traversal `..`, atau path absolut.
  - `server/prisma/migrations/migration_lock.toml` dengan `provider = "postgresql"`
  - Minimal satu `server/prisma/migrations/<nama_migrasi>/migration.sql` yang valid, non-empty, non-symlink, dan berisi SQL executable (bukan komentar atau `;` saja)
  - `server/prisma/seed.ts` (non-empty, non-symlink)
  - Direktori test khusus database `server/src/__tests__/database/*.test.ts` berisi minimal satu file test non-empty yang benar-benar dapat dijalankan
- **Script wajib pada `server/package.json` (harus satu direct local executable *fail-closed* dari dependency workspace tanpa wrapper `npx`/`npm`/`npm exec`, tanpa path `/` atau `\`, tanpa env prefix seperti `PATH=`/`NODE_PATH=`/`NODE_OPTIONS=`/`HOME=`/`IFS=`, dan tanpa `;`, `||`, `|`, `&&`, `&`, redirection, `$()`, backtick, placeholder, maupun unit test generik; hanya `NODE_ENV=test` yang diizinkan khusus pada `test:db`):**
  1. `db:validate` — `prisma validate --schema=prisma/schema.prisma`
  2. `db:migrate:deploy` — `prisma migrate deploy --schema=prisma/schema.prisma`
  3. `db:seed` — `tsx prisma/seed.ts`
  4. `test:db` — menjalankan database test directory memakai runner test bawaan dengan output TAP, misalnya:
     `node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts`
- **Ketentuan immutability & batas verifikasi test:**
  - Migration SQL yang sudah ada pada base branch (`main`) bersifat immutable (tidak boleh dihapus, disymlink, diubah, atau diganti nama pada Pull Request berikutnya), dan kegagalan resolusi base commit atau `git ls-tree` akan langsung menggagalkan CI (*fail-closed*). Penambahan migrasi baru dilakukan melalui direktori migrasi baru.
  - Setelah `server/prisma/schema.prisma` tersedia di `main`, Pull Request yang menghapus file tersebut otomatis digagalkan.
  - Output TAP dari `test:db` diperiksa oleh CI untuk memastikan minimal satu test berjalan dan lulus (`# tests > 0`, `# pass > 0`, `# fail == 0`, serta tidak seluruh test berstatus skip). Karena CI tidak memverifikasi isi AST setiap test apakah benar-benar memanggil Prisma/PostgreSQL, reviewer pada `SBS-19` wajib meninjau bahwa test menjalankan operasi database nyata, bukan mock-only atau assertion statis. Detail lengkap dijelaskan pada [`docs/ci.md`](../docs/ci.md).
