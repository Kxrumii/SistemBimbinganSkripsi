# Panduan & Log Pengujian — Sistem Bimbingan Skripsi (Kelompok A4)

Dokumen ini mendefinisikan skenario verifikasi fondasi aplikasi dan containerization (`SBS-04`) serta mencatat hasil eksekusi aktual.

---

## 1. Perintah Verifikasi Aplikasi

Jalankan seluruh pemeriksaan dari root repository setelah `npm ci`:

```bash
npm run typecheck
npm run lint
npm run build
npm test
```

### Cakupan Frontend (`client/`) & Backend (`server/`)
- `typecheck` & `lint`: Validasi TypeScript strict serta ESLint (`react-hooks`, `react-refresh`, dan aturan unused vars) tanpa error/warning.
- `build`: Menghasilkan `client/dist/` (Vite + Tailwind CSS v4) dan `server/dist/` (`tsc -p tsconfig.build.json`).
- `npm test` (`server/src/__tests__/health.test.ts`):
  - Validasi `loadEnv` (`NODE_ENV`, `API_HOST` default `127.0.0.1` dan override `0.0.0.0`, penolakan `API_HOST` tidak valid, `DATABASE_URL` wajib, `API_PORT`, serta penolakan `CLIENT_ORIGIN` wildcard `*`).
  - `GET /api/v1/health` mengembalikan `200`, struktur JSON standar API Contract, dan bebas credential/path.
  - Rute tidak dikenal mengembalikan `404` (`NOT_FOUND`) dan JSON rusak mengembalikan `400` (`INVALID_JSON`).
  - Safeguard logging (`createErrorHandler`, `redactSensitiveMessage`): respons `500` generik; log production tidak mencetak `err.message` mentah maupun secret/URL database; log development meredaksi connection string, token, dan password.

---

## 2. Skenario Pengujian Development Lokal (Mode A)

1. **Database Development (`compose.dev.yaml`):**
   - Validasi config gabungan dengan project terisolasi:
     `docker compose -p sbs04-dev-final -f compose.yaml -f compose.dev.yaml config --quiet`
   - Jalankan `up -d db`; verifikasi `db` berstatus `healthy`, port hanya terikat ke `127.0.0.1:5432->5432/tcp` (bukan `0.0.0.0`), dan PostgreSQL merespons koneksi dari host `127.0.0.1:5432`.
2. **API Bind Address Lokal & Vite Proxy:**
   - Jalankan `npm run dev` dengan `API_HOST=127.0.0.1`.
   - Verifikasi socket listener Express hanya pada `127.0.0.1:3000` (bukan `0.0.0.0:3000`).
   - Verifikasi frontend `http://127.0.0.1:5173/` (`200`) dan Vite proxy `http://127.0.0.1:5173/api/v1/health` (`200` JSON `status: "ok"`).
   - Hentikan DB uji dengan `stop db` tanpa menghapus volume.

---

## 3. Skenario Pengujian Full Stack Compose, Keamanan & Persistensi (Mode B)

Gunakan project terisolasi (`-p sbs04-final`) dan file env sementara di luar Git:

```bash
docker compose --env-file /tmp/sbs04-final.env -p sbs04-final config --quiet
docker compose --env-file /tmp/sbs04-final.env -p sbs04-final build
docker compose --env-file /tmp/sbs04-final.env -p sbs04-final up -d
docker compose --env-file /tmp/sbs04-final.env -p sbs04-final ps
```

Daftar pemeriksaan yang wajib lulus:
1. **Healthcheck:** `db`, `api`, dan `web` ketiganya berstatus `running (healthy)`.
2. **Endpoint & Proxy:** `/healthz` (`200 ok`), `/` (HTML starter), `/api/v1/health` (`200` JSON sesuai API Contract), `/api/v1/unknown` (`404 NOT_FOUND`).
3. **Port Exposure & Network Isolation:** `db` dan `api` memiliki `host_published=[]`; `web` hanya mempublikasikan `127.0.0.1:${WEB_PORT}->8080/tcp`; jaringan `internal` memiliki `Internal=true`; `api` memakai hostname `db:5432`.
4. **Nginx Upload Request Limit:** `docker compose ... exec -T web nginx -t` lulus, dan `nginx -T` menampilkan `client_max_body_size 12m;` pada scope `location /api/`. *(Limit bisnis 10 MiB tetap ditegakkan backend pada `SBS-09`; uji upload berkas sebenarnya bukan bagian `SBS-04`.)*
5. **Non-root Runtime:** `api` berjalan sebagai `uid=1000(node)` dan `web` berjalan sebagai `uid=101(nginx)`.
6. **Secrets & Image Hygiene:** `.env` tidak ada di image container (`/app/.env` absen), `docker compose logs` bebas credential, dan repo bebas penyebutan host privat serta bebas `localStorage`/`sessionStorage`.
7. **Volume Persistence & Privasi Upload:** Tabel penanda sintetis pada `sbs_pgdata` dan file penanda pada `/app/storage/revisions` (`sbs_uploads`) bertahan setelah `restart db api` maupun `up -d --force-recreate`, tidak dapat diunduh melalui URL `web`, lalu dibersihkan sebelum `docker compose down` (tanpa `-v`).

---

## 4. Pemisahan Pengujian Lokal, Automated CI Checks, dan Tahap Pasca-`SBS-19`

1. **Pengujian lokal:** Dijalankan pengembang sebelum push (`npm run typecheck`, `npm run lint`, `npm run build`, `npm test`, serta smoke test lokal Mode A `compose.dev.yaml` atau Mode B `compose.yaml`).
2. **Automated CI checks (GitHub Actions):** Berjalan otomatis pada `pull_request` dan `push` ke `main` melalui [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), mencakup:
   - **`Quality Gate`:** `npm ci`, `typecheck`, `lint`, `build`, dan unit tests pada Node.js `22.x`.
   - **`Docker Compose Integration`:** validasi `compose.yaml` dan `compose.dev.yaml`, build image, healthcheck `db`/`api`/`web`, smoke test `/`, `/healthz`, `/api/v1/health`, `pg_isready` & `SELECT 1`, serta verifikasi isolasi port, jaringan `Internal=true`, dan mount volume.
3. **Database schema, migration, dan integrity tests (menunggu `SBS-19`):** Pengujian Prisma (`prisma validate`, `prisma migrate deploy`, seed sintetis, serta uji constraint dan relasi database) belum tersedia dan belum dijalankan di CI sampai implementasi `SBS-19` di-merge ke `main`. Pengujian fitur bisnis (`SBS-05`–`SBS-12`) dan domain online (`SBS-13`–`SBS-15`) menyusul pada Issue masing-masing.

---

## 5. Log Hasil Pengujian

### Final Verification Gate `SBS-04` (26 November 2026)

- **Aplikasi (`npm ci --offline`, `npm run typecheck`, `npm run lint`, `npm run build`, `npm test`):**
  - `npm ci --offline`: Lulus (`285` packages tersinkron dengan root `package-lock.json`).
  - `npm run typecheck`: Lulus untuk `sbs-client` dan `sbs-server`.
  - `npm run lint`: Lulus tanpa error maupun warning pada `client` dan `server`.
  - `npm run build`: `client/dist/` (Vite `545ms`) dan `server/dist/` (`tsc -p tsconfig.build.json`) berhasil.
  - `npm test`: `10/10` tests pada `3` suite lulus (`loadEnv validation` 4/4, `Express API foundation` 3/3, `Error logging safeguards` 3/3).
- **Development Workflow (`-p sbs04-dev-final`, `compose.yaml` + `compose.dev.yaml`):**
  - `docker compose ... up -d db`: PostgreSQL 16 berstatus `healthy`, port hanya terikat ke `127.0.0.1:5432->5432/tcp`, wire protocol pada `127.0.0.1:5432` merespons normal.
  - `npm run dev` (`API_HOST=127.0.0.1`): Express mendengarkan pada `127.0.0.1:3000` (bukan `0.0.0.0`), `http://127.0.0.1:5173/` (`200` HTML), `http://127.0.0.1:5173/api/v1/health` (`200` JSON `status: "ok"`), dihentikan bersih via `stop db`.
- **Full Stack Compose (`-p sbs04-final`, `compose.yaml` saja):**
  - `docker compose ... config --quiet` & `build` & `up -d`: Ketiga service (`db`, `api`, `web`) mencapai status `running (healthy)`.
  - Endpoint via `web`: `GET /healthz` (`200 ok`), `GET /` (`200` HTML), `GET /api/v1/health` (`200` JSON `status: "ok"`).
  - Isolasi & Runtime: `api` dan `db` `host_published=[]`, jaringan `internal` memiliki `Internal=true`, `api` memakai host DB `db:5432`, `api` berjalan sebagai `uid=1000(node)`, `web` berjalan sebagai `uid=101(nginx)` (`nginx version: nginx/1.30.6`), `nginx -t` lulus, `nginx -T` memuat `client_max_body_size 12m;` pada `location /api/`.
  - Keamanan & Persistensi: `.env` absen di image, log bebas credential, `git diff --check` bersih, `rg` bebas penyebutan host privat dan `localStorage`/`sessionStorage`; penanda sementara DB & `/app/storage/revisions` tidak bocor via `web`, bertahan setelah `restart db api` dan `up -d --force-recreate`, lalu dibersihkan sebelum `down` (tanpa `-v`).
