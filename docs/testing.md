# Panduan & Log Pengujian — Sistem Bimbingan Skripsi (Kelompok A4)

Dokumen ini berisi panduan verifikasi untuk fondasi aplikasi (`SBS-04`) serta catatan hasil pengujian aktual yang benar-benar telah dijalankan.

---

## 1. Perintah Verifikasi Aplikasi

Jalankan seluruh pemeriksaan berikut dari root repository setelah `npm install`:

```bash
npm run typecheck
npm run lint
npm run build
npm test
```

### Cakupan Pemeriksaan Frontend (`client/`)
- `npm run typecheck --workspace=client`: validasi TypeScript (`tsconfig.app.json` dan `tsconfig.node.json`).
- `npm run lint --workspace=client`: validasi aturan ESLint, `react-hooks`, dan `react-refresh`.
- `npm run build --workspace=client`: menghasilkan bundle produksi Vite + Tailwind CSS ke `client/dist/`.

### Cakupan Pemeriksaan Backend (`server/`)
- `npm run typecheck --workspace=server`: validasi TypeScript strict pada `server/src/`.
- `npm run lint --workspace=server`: validasi ESLint pada `server/src/`.
- `npm run build --workspace=server`: kompilasi TypeScript ke `server/dist/`.
- `npm test --workspace=server`: menjalankan unit/integration test (`server/src/__tests__/health.test.ts`):
  - Validasi environment positif dan negatif (`loadEnv`: menolak `DATABASE_URL` kosong, `API_PORT` tidak valid, atau `CLIENT_ORIGIN` wildcard `*`).
  - `GET /api/v1/health` mengembalikan HTTP `200`, struktur JSON konsisten, dan tidak membocorkan secret/path/config.
  - Rute tidak dikenal mengembalikan `404` (`NOT_FOUND`).
  - Payload JSON rusak mengembalikan `400` (`INVALID_JSON`).

---

## 2. Pemeriksaan Docker Compose & Smoke Test

Untuk menguji tanpa mengganggu volume aktif atau data lain, gunakan project name terisolasi (misalnya `-p sbs_smoke_sbs04`) dan file env sementara di luar Git:

```bash
docker compose --env-file /tmp/sbs04-smoke.env -p sbs_smoke_sbs04 config --quiet
docker compose --env-file /tmp/sbs04-smoke.env -p sbs_smoke_sbs04 build
docker compose --env-file /tmp/sbs04-smoke.env -p sbs_smoke_sbs04 up -d
docker compose --env-file /tmp/sbs04-smoke.env -p sbs_smoke_sbs04 ps
```

Pemeriksaan smoke test yang wajib lulus:
1. Seluruh service (`db`, `api`, `web`) mencapai status `healthy`.
2. Endpoint web & proxy merespons benar:
   - `curl -fsS http://127.0.0.1:8080/healthz` -> `ok`
   - `curl -fsS http://127.0.0.1:8080/` -> HTML starter aplikasi
   - `curl -fsS http://127.0.0.1:8080/api/v1/health` -> JSON `success: true`, `data.status: "ok"`
3. Isolasi port dan jaringan:
   - Service `db` dan `api` tidak memiliki port binding ke host.
   - Service `web` hanya mempublikasikan port ke `127.0.0.1`.
   - Service `api` berjalan sebagai user non-root `node` dan `web` berjalan sebagai user non-root `nginx`.
4. Kebersihan log dan image:
   - `docker compose logs` tidak mencetak password database atau secret.
   - File `.env` tidak ada di dalam image container.

---

## 3. Pemeriksaan Persistensi Volume

Uji ketahanan data sementara (tanpa data nyata) pada `sbs_pgdata` dan `sbs_uploads`:
1. Buat tabel penanda sementara pada `db` dan file penanda sementara di `/app/storage/revisions/` pada container `api`.
2. Pastikan file penanda pada `/app/storage/revisions/` tidak dapat diakses melalui HTTP endpoint `web`.
3. Restart `db` dan `api`, lalu lakukan recreate (`docker compose ... up -d --force-recreate`).
4. Verifikasi tabel penanda di PostgreSQL dan file penanda di `api` masih ada dan dapat dibaca.
5. Hapus tabel dan file penanda sementara, lalu hentikan stack smoke test dengan `docker compose ... down` (**jangan pernah menjalankan `down -v` pada data aktif**).

---

## 4. Ruang Lingkup Pengujian Fitur Berikutnya

Pengujian fitur bisnis (autentikasi, cookie `HttpOnly`, CSRF, RBAC, pengajuan/persetujuan judul, pembimbing, jadwal bimbingan, upload PDF/DOCX <= 10 MiB, catatan dosen *append-only*, serta monitoring progres) dijadwalkan pada Issue `SBS-19`, `SBS-05`–`SBS-13`.

---

## 5. Log Hasil Pengujian

### Pengujian `SBS-04` (26 November 2026)

- **Lingkungan:** Host pengembangan lokal & Docker Compose terisolasi (`-p sbs_smoke_sbs04`)
- **Aplikasi (`npm run typecheck`, `npm run lint`, `npm run build`, `npm test`):**
  - `npm run typecheck`: Lulus untuk `client` dan `server`.
  - `npm run lint`: Lulus tanpa error/warning pada `client` dan `server`.
  - `npm run build`: Bundle produksi `client/dist/` (`dist/index.html`, CSS, JS) dan kompilasi `server/dist/` berhasil.
  - `npm test`: `6` pengujian pada `2` suite lulus (`loadEnv validation` 3/3, `Express API foundation` 3/3).
  - Smoke dev (`npm run dev`): Frontend (`http://127.0.0.1:5173/`) dan proxy `/api/v1/health` ke Express (`0.0.0.0:3000`) merespons `200 OK`.
- **Docker Compose & Persistensi (`config`, `build`, `up -d`, `ps`, `restart`, `up -d --force-recreate`, `down`):**
  - `docker compose config --quiet` dan `docker compose build`: Lulus untuk `web` dan `api`.
  - `docker compose ps`: `db`, `api`, dan `web` ketiganya berstatus `running (healthy)`.
  - Endpoint HTTP via `web`: `GET /healthz` (`200 ok`), `GET /` (`200` HTML), `GET /api/v1/health` (`200` JSON `status: "ok"`), `GET /api/v1/unknown` (`404` `NOT_FOUND`).
  - Isolasi & Runtime: `db` dan `api` tidak mempublikasikan port host (`host_published=[]`); `web` hanya terikat pada `127.0.0.1:8080->8080/tcp`; jaringan `internal` memiliki `Internal=true`; `api` berjalan sebagai `uid=1000(node)` dan `web` sebagai `uid=101(nginx)`; `.env` tidak ada di image; log bebas credential.
  - Persistensi & Pembersihan: Data penanda sementara pada PostgreSQL (`sbs_pgdata`) dan direktori `/app/storage/revisions` (`sbs_uploads`) bertahan setelah `restart db api` dan `up -d --force-recreate`, tidak dapat diakses via path publik `web`, dan dibersihkan sebelum `docker compose down` (tanpa `-v`).
