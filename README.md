# Sistem Bimbingan Skripsi — Kelompok A4

Aplikasi web pengajuan judul dan pemantauan proses bimbingan skripsi untuk Tugas Besar Pengembangan Aplikasi Web (PAW) Kelompok A4.

- **Repository:** https://github.com/Kxrumii/SistemBimbinganSkripsi
- **Domain target:** `https://sbs.kxrumii.my.id` *(deployment produksi dijadwalkan pada `SBS-14`)*

> **Status Repository:** Fondasi aplikasi (`client/`, `server/`) dan orkestrasi container Docker Compose (`compose.yaml`) tersedia pada branch kerja `SBS-04`. Schema Prisma/database (`SBS-19`), autentikasi/RBAC (`SBS-05`–`SBS-06`), fitur bisnis akademik (`SBS-07`–`SBS-11`), shared frontend UI (`SBS-12`), dan deployment server (`SBS-14`) dikerjakan pada Issue masing-masing.

---

## Deskripsi Aplikasi

Aplikasi ini dirancang untuk mengelola alur bimbingan skripsi secara terstruktur antara administrator (`ADMIN`), dosen pembimbing (`DOSEN`), dan mahasiswa (`MAHASISWA`). Sistem mengandalkan basis data relasional PostgreSQL 16, kontrol akses di sisi backend, serta pencatatan riwayat revisi dan catatan dosen secara persisten.

---

## Fitur Target (Kelompok A4)

1. **Pengajuan judul skripsi** (`SBS-07`) — satu pengajuan aktif per mahasiswa; pengajuan ulang membuat record baru tanpa menghapus histori.
2. **Persetujuan judul** (`SBS-07`) — administrator meninjau dan memutus pengajuan; persetujuan membentuk entitas skripsi secara atomik.
3. **Penetapan dosen pembimbing** (`SBS-06`) — satu pembimbing utama aktif per skripsi dengan histori assignment terjaga.
4. **Jadwal bimbingan** (`SBS-08`) — pengajuan, konfirmasi, penolakan, usulan waktu baru, pembatalan beralasan, dan pencegahan benturan jadwal dosen.
5. **Upload berkas revisi** (`SBS-09`) — berkas PDF/DOCX maksimal 10 MiB (`10.485.760` byte) ke penyimpanan privat berversi (*append-only*) dengan unduhan terotorisasi.
6. **Catatan dosen** (`SBS-10`) — umpan balik bersifat *append-only*; koreksi dibuat sebagai catatan baru yang merujuk catatan sebelumnya.
7. **Monitoring progres** (`SBS-11`) — pelacakan tahapan proses dan lini masa milestone berbasis peristiwa database, dilengkapi pencarian, filter, dan dashboard per peran.

---

## Stack Teknologi

- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS v4 (`client/`)
- **Backend:** Express.js + TypeScript (`server/`)
- **ORM:** Prisma *(integrasi schema & migrasi pada `SBS-19`)*
- **Database:** PostgreSQL 16 (`postgres:16-alpine` pada internal Docker network)
- **Containerization:** Docker & Docker Compose (`client/Dockerfile`, `server/Dockerfile`, `compose.yaml`)
- **Web Serving & Reverse Proxy Kontainer:** Nginx unprivileged (`client/nginx.conf`)
- **Lingkungan Deployment Target:** Server Linux dengan Docker Engine, Docker Compose, Nginx, dan Cloudflare Tunnel (`SBS-14`)

---

## Struktur Monorepo

```text
SistemBimbinganSkripsi/
├── .github/
│   └── pull_request_template.md   # Template Pull Request
├── .gitattributes                 # Normalisasi line ending dan aturan file biner
├── .gitignore                     # Pengecualian node_modules, dist, .env, dan storage
├── .dockerignore                  # Pengecualian artefak lokal pada build context Docker
├── .env.example                   # Template placeholder environment variables
├── compose.yaml                   # Orkestrasi service db, api, dan web
├── package.json                   # Root npm workspaces dan scripts bersama
├── scripts/
│   └── dev.mjs                    # Runner development server client + server bersamaan
├── client/
│   ├── Dockerfile                 # Multi-stage build frontend + Nginx non-root
│   ├── nginx.conf                 # Static serving + proxy /api/ ke service api
│   ├── eslint.config.js
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts             # Konfigurasi Vite + Tailwind CSS + dev proxy /api
│   └── src/
│       ├── App.tsx                # Starter UI + pengecekan GET /api/v1/health
│       ├── index.css
│       ├── main.tsx
│       └── lib/apiClient.ts       # HTTP client terpusat dengan prefix /api/v1
├── server/
│   ├── Dockerfile                 # Multi-stage build backend Node.js non-root
│   ├── eslint.config.js
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.build.json
│   └── src/
│       ├── app.ts                 # Konfigurasi Express app, Helmet, CORS, prefix /api/v1
│       ├── server.ts              # Startup server (listen 0.0.0.0) & graceful shutdown
│       ├── config/env.ts          # Pemuatan & validasi environment variables saat startup
│       ├── middlewares/           # notFoundHandler dan errorHandler
│       ├── modules/               # Direktori modul fitur (SBS-05 s.d. SBS-11)
│       ├── routes/                # Router dasar & GET /api/v1/health
│       ├── utils/appError.ts
│       └── __tests__/health.test.ts
├── database/
│   └── README.md                  # Kontrak service PostgreSQL 16 untuk SBS-03 & SBS-19
├── infra/
│   └── README.md                  # Catatan batas jaringan kontainer untuk SBS-14 & SBS-15
└── docs/
    ├── deployment.md              # Panduan Docker Compose, healthcheck, dan persistensi
    └── testing.md                 # Panduan verifikasi aplikasi, Compose, dan smoke test
```

---

## Status Implementasi Aktual

| Area | Status Saat Ini | Keterangan |
|---|---|---|
| Bootstrap Repository (`SBS-01`) | Selesai | Struktur monorepo, ignore files, `.env.example`, template PR tersedia. |
| Proposal & Dokumentasi (`SBS-02`) | Selesai | Proposal, analisis kebutuhan, dan dokumentasi proyek disusun. |
| Use Case, ERD & Kontrak (`SBS-03`) | Pending | Menunggu pengerjaan Paket 1. |
| Application Foundation & Containerization (`SBS-04`) | Siap direview | Workspace `client/`, `server/`, `Dockerfile`, `compose.yaml`, healthcheck, dan uji persistensi terverifikasi pada branch `SBS-04`. |
| Database Prisma (`SBS-19`) | Pending | Menunggu pengerjaan Paket 1 (menggunakan `DATABASE_URL` dan service `db`). |
| Autentikasi & Fitur Bisnis (`SBS-05`–`SBS-12`) | Pending | Menunggu pengerjaan Paket 3–6 pada direktori `server/src/modules/` dan `client/src/`. |
| Integrasi, Keamanan & Deployment (`SBS-13`–`SBS-15`) | Pending | Dikerjakan setelah modul inti selesai. |

---

## Prasyarat

- **Git**
- **Node.js** `>= 22` (LTS) dan **npm** `>= 10`
- **Docker Engine** dan **Docker Compose** v2 (`docker compose`)

---

## Instalasi Dependency & Pengembangan Lokal

1. Clone repository dan checkout branch Issue Anda:
   ```bash
   git clone https://github.com/Kxrumii/SistemBimbinganSkripsi.git
   cd SistemBimbinganSkripsi
   git fetch origin
   ```
2. Install seluruh dependency monorepo dari root (menggunakan satu root `package-lock.json`):
   ```bash
   npm install
   ```
3. Salin template environment menjadi `.env` dan sesuaikan nilai placeholder (`CHANGE_ME_*`):
   ```bash
   cp .env.example .env
   ```
   > Pastikan `.env` tidak pernah di-commit ke Git.

4. Jalankan mode development:
   - **Frontend dan backend sekaligus:**
     ```bash
     npm run dev
     ```
   - **Terpisah per workspace:**
     ```bash
     npm run dev:server
     npm run dev:client
     ```
   - Frontend dev berjalan di `http://localhost:5173` dan meneruskan request `/api/*` ke `http://127.0.0.1:3000` (sesuai `API_PORT`).
   - Backend API mensyaratkan `DATABASE_URL` berformat `postgres://` atau `postgresql://` serta `UPLOAD_DIR` terdefinisi di `.env` saat startup.

---

## Menjalankan Stack dengan Docker Compose

1. Pastikan file `.env` sudah terisi nilai non-placeholder untuk `POSTGRES_DB`, `POSTGRES_USER`, dan `POSTGRES_PASSWORD`. Jika menguji akses melalui Compose pada host yang sama, Anda dapat menyesuaikan `CLIENT_ORIGIN=http://127.0.0.1:8080`.
2. Validasi konfigurasi, build image, dan jalankan seluruh service:
   ```bash
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```
3. Verifikasi akses lokal (hanya service `web` yang di-bind ke loopback `127.0.0.1:${WEB_PORT:-8080}`):
   - Frontend: `http://127.0.0.1:8080/`
   - Nginx readiness: `http://127.0.0.1:8080/healthz`
   - API health melalui reverse proxy: `http://127.0.0.1:8080/api/v1/health`
4. Lihat log atau hentikan container tanpa menghapus volume data:
   ```bash
   docker compose logs -f
   docker compose down
   ```
   > **Peringatan:** Jangan menjalankan `docker compose down -v` pada lingkungan yang sudah menyimpan data karena `-v` akan menghapus named volume `sbs_pgdata` dan `sbs_uploads`.

---

## Perintah Build dan Verifikasi

Jalankan dari root repository:

```bash
npm run typecheck
npm run lint
npm run build
npm test
```

Command per workspace juga tersedia:
- `npm run build:client`
- `npm run build:server`

---

## Dokumentasi Terkait

- [Panduan Deployment & Operasional Kontainer](docs/deployment.md)
- [Panduan & Log Pengujian](docs/testing.md)
- [Template Pull Request](.github/pull_request_template.md)
