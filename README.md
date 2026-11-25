# Sistem Bimbingan Skripsi — Kelompok A4

Aplikasi web pengajuan judul dan pemantauan proses bimbingan skripsi untuk Tugas Besar Pengembangan Aplikasi Web (PAW) Kelompok A4.

- **Repository:** https://github.com/Kxrumii/SistemBimbinganSkripsi
- **Domain target:** `https://sbs.kxrumii.my.id` *(belum aktif / belum di-deploy)*

> **Status Repository:** Baseline awal monorepo (`SBS-01` dan `SBS-02`) tersedia di branch `main`.
> Source code aplikasi (`client/`, `server/`), schema Prisma, API endpoint, autentikasi, fitur bisnis, konfigurasi Docker (`Dockerfile`, `compose.yaml`), pengujian aplikasi, dan deployment belum dikerjakan.

---

## Deskripsi Aplikasi

Aplikasi ini dirancang untuk mengelola alur bimbingan skripsi secara terstruktur antara administrator, dosen pembimbing, dan mahasiswa. Sistem mengandalkan basis data relasional, kontrol akses di sisi backend, serta pencatatan riwayat revisi dan catatan dosen secara persisten.

---

## Fitur Utama

Tujuh fitur wajib Kelompok A4 berikut masih berupa target rancangan dan belum diimplementasikan:

1. **Pengajuan judul skripsi** — setiap mahasiswa hanya memiliki satu pengajuan aktif; pengajuan ulang setelah penolakan atau penarikan membuat record baru tanpa menghapus histori.
2. **Persetujuan judul** — administrator meninjau dan memutus pengajuan; persetujuan membentuk satu entitas skripsi secara atomik.
3. **Penetapan dosen pembimbing** — setiap skripsi memiliki satu pembimbing utama aktif, dengan histori yang tetap tersimpan saat terjadi pergantian.
4. **Jadwal bimbingan** — mahasiswa mengajukan jadwal, lalu dosen pembimbing mengonfirmasi, menolak, atau mengusulkan waktu baru; *reschedule* berlaku setelah disetujui pihak penerima, pembatalan mencatat alasan, dan sistem mencegah benturan jadwal dosen.
5. **Upload berkas revisi** — unggah berkas PDF atau DOCX maksimal 10 MiB (`10.485.760` byte) per file ke penyimpanan privat berversi (*append-only*) dengan unduhan terotorisasi.
6. **Catatan dosen** — catatan umpan balik bersifat *append-only*; koreksi dibuat sebagai catatan baru yang merujuk catatan sebelumnya.
7. **Monitoring progres** — pelacakan tahapan proses dan lini masa milestone yang diturunkan dari peristiwa bisnis di database (tanpa input persentase manual), dilengkapi pencarian, filter, dan dashboard per peran.

---

## Jenis Pengguna

| Peran (`Role`) | Ruang Lingkup Akses Target |
|---|---|
| `ADMIN` | Mengelola akun pengguna, meninjau dan memutus pengajuan judul, menetapkan atau mengganti pembimbing utama aktif, serta memantau keseluruhan proses. |
| `DOSEN` | Mengakses data mahasiswa bimbingan aktifnya, mengelola jadwal bimbingan, mengunduh berkas revisi mahasiswa bimbingan, menulis dan membaca catatan dosen, serta memantau progres. |
| `MAHASISWA` | Mengelola pengajuan judul, permintaan jadwal, dan unggahan revisi miliknya sendiri, serta membaca catatan dosen dan progres skripsinya. |

Seluruh batas akses peran dan kepemilikan data ditegakkan di setiap endpoint backend.

---

## Stack Teknologi

Daftar berikut adalah stack baseline yang dipilih dan belum diimplementasikan sebagai source code aplikasi:

- **Frontend:** React + Vite + Tailwind CSS
- **Backend:** Express.js + TypeScript
- **ORM:** Prisma
- **Database:** PostgreSQL 16 (pada internal Docker network)
- **Password Hashing:** bcrypt
- **Authentication:** JWT dalam `HttpOnly` `Secure` Cookie (`SameSite=Lax`) dengan proteksi CSRF
- **Lingkungan Deployment:** Server Linux dengan Docker Engine dan Docker Compose
- **Reverse Proxy:** Nginx
- **Public Ingress & TLS:** Cloudflare Tunnel menuju domain target `sbs.kxrumii.my.id` (HTTPS)

---

## Struktur Monorepo

```text
SistemBimbinganSkripsi/
├── .github/
│   └── pull_request_template.md   # Template Pull Request
├── .gitattributes                 # Normalisasi line ending dan aturan file biner
├── .gitignore                     # Pengecualian dependency, output build, dan secrets
├── .dockerignore                  # Pengecualian build context Docker
├── .env.example                   # Template placeholder environment variables
├── README.md                      # Dokumentasi utama repository
├── client/
│   └── src/                       # Source code frontend (belum berisi kode aplikasi)
├── server/
│   └── src/                       # Source code backend dan Prisma (belum berisi kode aplikasi)
├── infra/                         # Konfigurasi infrastruktur dan deployment (placeholder)
├── database/                      # Artefak database dan ERD (placeholder)
└── docs/
    ├── deployment.md              # Kerangka arsitektur dan panduan deployment
    └── testing.md                 # Kerangka panduan dan log pengujian
```

---

## Status Implementasi Aktual

| Area | Status Saat Ini | Keterangan |
|---|---|---|
| Bootstrap Repository (`SBS-01`) | Selesai (baseline lokal) | Struktur monorepo, file ignore, `.env.example`, dan template PR tersedia. |
| Proposal, Analisis & Dokumentasi Publik (`SBS-02`) | Selesai (baseline lokal) | Proposal dan analisis kebutuhan disusun di dokumentasi proyek; `README.md` dan `docs/deployment.md` diselaraskan dengan standar penamaan eksternal. |
| Rancangan Use Case, ERD & Kontrak (`SBS-03`) | Belum dikerjakan | Use Case Diagram, ERD final, dan schema Prisma belum tersedia. |
| Containerization (`Dockerfile`, `compose.yaml`) | Belum dikerjakan | Baru tersedia `.dockerignore`. |
| Aplikasi Frontend & Backend (`client/`, `server/`) | Belum dikerjakan | Belum ada source code, endpoint, autentikasi, atau UI. |
| Pengujian & Deployment | Belum dilakukan | Aplikasi belum dijalankan secara lokal maupun di-deploy ke `https://sbs.kxrumii.my.id`. |

---

## Prasyarat

Untuk tahap baseline saat ini:
- **Git**

Untuk tahap pengembangan dan containerization berikutnya:
- **Node.js** (LTS) dan package manager
- **Docker Engine** dan **Docker Compose**
- **PostgreSQL 16** (melalui container atau instalasi lokal saat backend mulai dikembangkan)

---

## Panduan Setup Lokal

1. Clone repository:
   ```bash
   git clone https://github.com/Kxrumii/SistemBimbinganSkripsi.git
   cd SistemBimbinganSkripsi
   ```
2. Salin template environment untuk persiapan lokal:
   ```bash
   cp .env.example .env
   ```
   Sesuaikan nilai placeholder di `.env` dan pastikan file `.env` maupun credential nyata tidak pernah masuk ke commit Git.

> **Catatan:** Aplikasi frontend (`client/`), backend (`server/`), schema Prisma, `Dockerfile`, dan `compose.yaml` belum tersedia pada tahap ini sehingga aplikasi belum dapat dijalankan. Panduan instalasi dependency, migrasi database, build, dan menjalankan service akan ditambahkan setelah implementasi terkait dibuat.

---

## Dokumentasi Terkait

- [Panduan Deployment](docs/deployment.md)
- [Panduan & Log Pengujian](docs/testing.md)
- [Template Pull Request](.github/pull_request_template.md)
