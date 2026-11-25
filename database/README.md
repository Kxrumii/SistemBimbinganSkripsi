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
