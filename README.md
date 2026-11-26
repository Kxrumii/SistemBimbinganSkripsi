# Sistem Bimbingan Skripsi — Kelompok A4

Aplikasi web pengajuan judul dan pemantauan proses bimbingan skripsi untuk Tugas Besar Pengembangan Aplikasi Web (PAW) Kelompok A4.

- **Repository:** https://github.com/Kxrumii/SistemBimbinganSkripsi
- **Domain target:** `https://sbs.kxrumii.my.id` *(deployment produksi dijadwalkan pada `SBS-14`)*

> **Status Repository:** Fondasi aplikasi (`client/`, `server/`), orkestrasi container Docker Compose (`compose.yaml`, `compose.dev.yaml`), serta pipeline GitHub Actions CI (`.github/workflows/ci.yml`) sudah tersedia di repository. Schema Prisma/database (`SBS-19`), autentikasi/RBAC (`SBS-05`–`SBS-06`), fitur bisnis akademik (`SBS-07`–`SBS-11`), shared frontend UI (`SBS-12`), dan deployment server (`SBS-14`) dikerjakan pada Issue masing-masing.

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
- **Containerization:** Docker & Docker Compose (`client/Dockerfile`, `server/Dockerfile`, `compose.yaml`, `compose.dev.yaml`)
- **Web Serving & Reverse Proxy Kontainer:** Nginx unprivileged (`nginxinc/nginx-unprivileged:1.30.6-alpine` pada `client/nginx.conf`)
- **Lingkungan Deployment Target:** Server Linux dengan Docker Engine, Docker Compose, Nginx, dan Cloudflare Tunnel (`SBS-14`)

---

## Struktur Monorepo

```text
SistemBimbinganSkripsi/
├── .github/
│   ├── pull_request_template.md       # Template Pull Request
│   ├── scripts/
│   │   ├── validate_db_contract.py    # Validator kontrak SBS-19 & output TAP
│   │   └── test_validate_db_contract.py
│   └── workflows/
│       └── ci.yml                     # GitHub Actions CI (3 job checks)
├── .gitattributes                 # Normalisasi line ending dan aturan file biner
├── .gitignore                     # Pengecualian node_modules, dist, .env, dan storage
├── .dockerignore                  # Pengecualian artefak lokal pada build context Docker
├── .env.example                   # Template placeholder environment variables
├── compose.yaml                   # Orkestrasi utama full stack (db, api, web)
├── compose.dev.yaml               # Override khusus dev lokal untuk akses db di 127.0.0.1:5432
├── package.json                   # Root npm workspaces dan scripts bersama
├── package-lock.json              # Lockfile tunggal monorepo
├── scripts/
│   └── dev.mjs                    # Runner development server client + server bersamaan
├── client/
│   ├── Dockerfile                 # Multi-stage build frontend + Nginx 1.30.6 unprivileged
│   ├── nginx.conf                 # Static SPA serving + proxy /api/ (client_max_body_size 12m)
│   ├── eslint.config.js
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.app.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts             # Konfigurasi Vite + Tailwind CSS + dev proxy /api
│   └── src/
│       ├── App.tsx                # Starter UI + pengecekan GET /api/v1/health
│       ├── index.css
│       ├── main.tsx
│       ├── vite-env.d.ts
│       └── lib/apiClient.ts       # HTTP client terpusat dengan prefix /api/v1
├── server/
│   ├── Dockerfile                 # Multi-stage build backend Node.js 22 non-root
│   ├── eslint.config.js
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.build.json
│   └── src/
│       ├── app.ts                 # Konfigurasi Express app, Helmet, CORS, prefix /api/v1
│       ├── server.ts              # Startup server (API_HOST:API_PORT) & graceful shutdown
│       ├── config/env.ts          # Pemuatan & validasi environment variables saat startup
│       ├── middlewares/           # notFoundHandler dan createErrorHandler (redaksi log)
│       ├── modules/               # Direktori modul fitur (SBS-05 s.d. SBS-11)
│       ├── routes/                # Router dasar & GET /api/v1/health
│       ├── utils/appError.ts
│       └── __tests__/health.test.ts
├── database/
│   └── README.md                  # Kontrak service PostgreSQL 16 untuk SBS-03 & SBS-19
├── infra/
│   └── README.md                  # Catatan batas jaringan kontainer untuk SBS-14 & SBS-15
└── docs/
    ├── ci.md                      # Panduan GitHub Actions CI dan troubleshooting
    ├── deployment.md              # Panduan Mode A (Dev Lokal) & Mode B (Full Compose)
    └── testing.md                 # Panduan verifikasi aplikasi, Compose, dan smoke test
```

---

## Prasyarat

- **Git**
- **Node.js** `>= 22.0.0` (LTS) dan **npm** `>= 10.0.0`
- **Docker Engine** dan **Docker Compose** v2 (`docker compose`)
- **OpenSSL** *(untuk menghasilkan password acak URL-safe)*

---

## 1. Clone Repository dan Checkout Branch Issue

Setiap Issue dikerjakan pada remote branch yang sudah disiapkan oleh Project Owner. **Jangan** membuat branch baru secara manual menggunakan `git switch -c`.

Contoh untuk `SBS-04` (`#4`):

```bash
git clone https://github.com/Kxrumii/SistemBimbinganSkripsi.git
cd SistemBimbinganSkripsi
git fetch origin
git switch --track origin/issue/4-app-foundation-docker
```

Untuk Issue lain, ganti `issue/4-app-foundation-docker` dengan nama branch Issue terkait (misalnya `issue/5-authentication-rbac` untuk `#5`). Jika branch tersebut belum memiliki commit pekerjaan dan tertinggal dari `main`, jalankan `git merge --ff-only origin/main` sebelum mulai bekerja.

---

## 2. Instalasi Dependency

Install seluruh dependency monorepo dari root menggunakan root `package-lock.json` tunggal:

```bash
npm ci
```

*(Gunakan `npm install` hanya saat menambahkan atau memperbarui dependency sesuai persetujuan Issue terkait.)*

---

## 3. Konfigurasi Environment (`.env`)

1. Salin template environment di root repository:
   ```bash
   cp .env.example .env
   ```
2. Buat password PostgreSQL acak yang URL-safe (hex tanpa karakter khusus yang memecah URL):
   ```bash
   openssl rand -hex 32
   ```
3. Buka `.env`, pertahankan `POSTGRES_DB` dan `POSTGRES_USER` sebagai identifier sederhana (`[a-z0-9_]+`), lalu isi password hasil `openssl rand -hex 32` yang **sama persis** ke:
   - `POSTGRES_PASSWORD`
   - segmen password pada `DATABASE_URL` (`postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@127.0.0.1:5432/<POSTGRES_DB>?schema=public`)

> Jangan pernah meng-commit `.env` atau credential asli ke repository Git.

---

## 4. Menjalankan Database Development & Aplikasi Lokal

Gunakan workflow **Mode A (Development Lokal)** agar database PostgreSQL berjalan terisolasi pada loopback `127.0.0.1:5432` tanpa mengubah isolasi `compose.yaml` utama:

1. Nyalakan service database development (menggunakan project name terpisah `sbs-dev`):
   ```bash
   npm run dev:db:up
   ```
2. Jalankan frontend Vite dan backend Express secara bersamaan:
   ```bash
   npm run dev
   ```
   Atau jalankan secara terpisah:
   ```bash
   npm run dev:server
   npm run dev:client
   ```
   - Backend API mendengarkan pada `127.0.0.1:3000` (`API_HOST=127.0.0.1` secara default di `.env`).
   - Frontend dev berjalan di `http://127.0.0.1:5173` dan meneruskan request `/api/*` ke backend melalui Vite proxy.
3. Setelah selesai bekerja, hentikan database development **tanpa menghapus volume data**:
   ```bash
   npm run dev:db:down
   ```

---

## 5. Menjalankan Stack Penuh dengan Docker Compose

Untuk menguji seluruh stack container (`web`, `api`, dan `db`) sesuai kondisi produksi lokal, gunakan `compose.yaml` saja (**jangan** menyertakan `compose.dev.yaml`):

1. Pastikan `.env` sudah terisi credential valid. Jika menguji akses melalui `web` pada host yang sama, atur `CLIENT_ORIGIN=http://127.0.0.1:8080`.
2. Validasi, build, dan jalankan seluruh service:
   ```bash
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```
3. Verifikasi endpoint melalui satu listener loopback (`127.0.0.1:${WEB_PORT:-8080}`):
   - Frontend: `http://127.0.0.1:8080/`
   - Nginx health: `http://127.0.0.1:8080/healthz`
   - API health melalui proxy: `http://127.0.0.1:8080/api/v1/health`
4. Lihat log atau hentikan container tanpa menghapus volume:
   ```bash
   docker compose logs -f
   docker compose down
   ```
   > **Peringatan:** Jangan menjalankan `docker compose down -v` atau `docker volume prune` karena akan menghapus named volume `sbs_pgdata` dan `sbs_uploads`.

---

## 6. Perintah Build dan Verifikasi

Jalankan dari root repository sebelum membuat Pull Request:

```bash
npm run typecheck
npm run lint
npm run build
npm test
```

Perintah per workspace:
- `npm run build:client`
- `npm run build:server`

---

## 7. Continuous Integration (GitHub Actions)

Repository dilengkapi automated CI pada [`.github/workflows/ci.yml`](.github/workflows/ci.yml) untuk setiap Pull Request menuju `main`, push ke `main`, dan trigger manual (`workflow_dispatch`). Pipeline menjalankan tiga job: **`Quality Gate`** (typecheck, lint, build, dan unit tests Node.js `22.x`), kemudian **`Database Integration`** (PostgreSQL Mode A `127.0.0.1:5432`, proteksi anti-hapus schema, serta gate kondisional Prisma `db:validate`, `db:migrate:deploy`, `db:seed`, dan `test:db` mulai `SBS-19`) bersama **`Docker Compose Integration`** (validasi konfigurasi, build, healthcheck, smoke test, serta verifikasi isolasi port, jaringan, dan volume) secara paralel.

Workflow ini tidak melakukan deployment ke server atau publish image ke container registry. Penjelasan detail kontrak database, batas baseline sebelum `SBS-19`, dan panduan troubleshooting tersedia pada [Dokumentasi CI](docs/ci.md) serta [Panduan Pengujian](docs/testing.md).

---

## Dokumentasi Terkait

- [Panduan GitHub Actions CI](docs/ci.md)
- [Panduan Deployment & Mode Operasional](docs/deployment.md)
- [Panduan & Log Pengujian](docs/testing.md)
- [Kontrak Database (`database/README.md`)](database/README.md)
- [Kontrak Infrastruktur (`infra/README.md`)](infra/README.md)
- [Template Pull Request](.github/pull_request_template.md)
