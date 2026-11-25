# Database Foundation (`database/`)

Direktori ini disiapkan sebagai tempat dokumentasi rancangan ERD dan artefak pendukung basis data (`SBS-03` dan `SBS-19`).

## Kontrak Service PostgreSQL (dari `SBS-04`)

- **Service Docker Compose:** `db` (`postgres:16-alpine`) pada jaringan `internal` tanpa publikasi port ke host.
- **Named Volume:** `sbs_pgdata` terpasang pada `/var/lib/postgresql/data`.
- **Variabel Environment Runtime:** `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, dan `DATABASE_URL` (pada `compose.yaml`, `api` otomatis terhubung ke host `db:5432`).
- **Schema & Migrasi:** Implementasi `server/prisma/schema.prisma`, migration PostgreSQL, dan seed data sintetis dikerjakan pada **SBS-19**.
