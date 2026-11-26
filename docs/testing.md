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

## 4. Pemisahan Pengujian Lokal, Automated CI Checks, dan Pengujian Paket

Agar cakupan verifikasi antar tahap tidak tumpang tindih dan hasil pemeriksaan tidak diklaim secara keliru, proyek membagi lapisan pengujian sebagai berikut:

1. **Pengujian lokal (Developer):** Dijalankan sebelum push (`npm run typecheck`, `npm run lint`, `npm run build`, `npm test`, serta smoke test lokal Mode A `compose.dev.yaml` atau Mode B `compose.yaml`).
2. **`Quality Gate` (CI):** Memasang dependency dengan `npm ci`, menjalankan self-test validator kontrak CI (`test_validate_db_contract.py`), menjalankan verifikasi runtime terisolasi root `.env` Prisma `7.10.1` (`.github/scripts/verify_prisma_root_env.py` di direktori sementara tanpa menambah dependency proyek), serta menjalankan `typecheck`, `lint`, `build`, dan unit tests (`npm test`) pada Node.js `22.x`.
3. **`Database Integration` (CI):** Memisahkan empat komponen yang berbeda:
   - *CI validator self-tests (`test_validate_db_contract.py`):* Menguji helper `.github/scripts/validate_db_contract.py` (anti-bypass schema/migration, isi SQL, `migration_lock.toml`, kontrak script, parser AST `server/prisma7.config.ts` dengan root `.env` & `override: false`, serta parser TAP); **bukan** pengganti test database aplikasi.
   - *PostgreSQL smoke test Mode A:* Menyalakan service `db` (`127.0.0.1:5432`) dan memverifikasi `pg_isready` serta `SELECT 1` dari host runner.
   - *Prisma validation, migration, dan seed (`SBS-19`):* Memvalidasi pin exact versi **Prisma ORM `7.10.1`** (`prisma` dan `@prisma/client`), `package-lock.json`, canonical config `server/prisma7.config.ts`, serta menjalankan `db:validate`, `db:migrate:deploy` (`--schema=prisma/schema.prisma`), dan `db:seed` (`tsx prisma/seed.ts`) setelah `server/prisma/schema.prisma` tersedia.
   - *Database integration & integrity tests (`SBS-19`):* Menjalankan `test:db` pada `server/src/__tests__/database/*.test.ts` (format TAP) terhadap PostgreSQL CI yang aktif dan memverifikasi minimal satu test benar-benar lulus. Validator memastikan keberadaan file test, deklarasi `test()`/`it()`, direct local executable tanpa `npx`/`npm exec` dengan exact executable & env allowlist pada `test:db`, canonical config `server/prisma7.config.ts` tanpa config alias maupun `package.json#prisma`, canonical schema path `--schema=prisma/schema.prisma`, serta ringkasan TAP, namun tidak membuktikan secara statis bahwa seluruh test mengkueri database nyata; reviewer `SBS-19` tetap wajib memastikan pengujian memakai koneksi PostgreSQL/Prisma sungguhan dan bukan mock-only suite. Pada baseline saat ini sebelum `SBS-19`, Step Summary `Database Integration` melaporkan `PostgreSQL infrastructure` dan `CI validator self-tests` sebagai **`PASS`**, sedangkan `SBS-19 schema/script/migration contract` serta `Prisma application integration` dilaporkan **`N/A`** dan belum dijalankan (kecuali bila artefak parsial `SBS-19` ditemukan tanpa schema lengkap, yang langsung menggagalkan job).
4. **`Docker Compose Integration` (CI):** Validasi `compose.yaml` dan `compose.dev.yaml`, build image, healthcheck `db`/`api`/`web`, smoke test `/`, `/healthz`, `/api/v1/health`, `pg_isready` & `SELECT 1`, serta verifikasi isolasi port, jaringan `Internal=true`, dan mount volume.
5. **Pengujian fitur bisnis dan deployment (`SBS-05`–`SBS-15`):** Pengujian autentikasi, alur bimbingan skripsi, upload revisi, notifikasi, serta validasi domain dan deployment online dikerjakan bertahap pada Issue masing-masing.

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
