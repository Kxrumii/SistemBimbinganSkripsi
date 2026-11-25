# Panduan & Log Pengujian — Sistem Bimbingan Skripsi (Kelompok A4)

> **Status:** Kerangka awal dokumen pengujian. Pengujian aplikasi belum dilakukan karena source code frontend, backend, database, dan endpoint belum dibuat.

---

## 1. Status Pengujian Saat Ini

Belum ada pengujian aplikasi yang dijalankan. Repository saat ini masih berisi kerangka monorepo dan dokumentasi baseline.

## 2. Ruang Lingkup Pengujian Target

Saat aplikasi mulai diimplementasikan, pengujian akan mencakup skenario positif dan negatif untuk:

- **Autentikasi & Sesi:** Login, logout (penghapusan cookie dan pencabutan sesi di server), JWT pada `HttpOnly` `Secure` cookie, serta proteksi CSRF.
- **Otorisasi & Batas Akses (RBAC):**
  - `ADMIN`: mengelola pengguna, pengajuan, penetapan pembimbing, dan pemantauan keseluruhan.
  - `DOSEN`: hanya mengakses mahasiswa yang sedang menjadi bimbingannya.
  - `MAHASISWA`: hanya mengakses dan mengelola data skripsinya sendiri.
- **Tujuh Fitur Wajib Kelompok A4:**
  1. Pengajuan judul skripsi (maksimal satu pengajuan aktif per mahasiswa).
  2. Persetujuan judul.
  3. Penetapan dosen pembimbing (satu pembimbing utama aktif dengan histori assignment).
  4. Jadwal bimbingan (pengajuan, konfirmasi, penolakan, dan usulan waktu baru).
  5. Upload berkas revisi (PDF/DOCX, maksimal 10 MiB / `10.485.760` byte per file, penyimpanan privat dan berversi).
  6. Catatan dosen (*append-only*).
  7. Monitoring progres (tahapan proses dan histori milestone).
- **Pencarian, Filter, & Persistensi Database:** Memastikan data tersimpan di PostgreSQL 16 melalui Prisma ORM.
- **Pengujian Domain Online:** Verifikasi fungsional melalui `https://sbs.kxrumii.my.id` setelah deployment selesai.

## 3. Cara Menjalankan Pengujian

Bagian ini akan dilengkapi setelah setup project `client/` dan `server/` serta test runner tersedia.

## 4. Standar Pencatatan Hasil Uji

Setiap laporan pengujian yang dicatat di dokumen ini perlu mencantumkan:
- Tanggal dan lingkungan uji (lokal / staging / production `sbs.kxrumii.my.id`).
- Command aktual yang dijalankan.
- Hasil aktual (jumlah lulus/gagal sesuai hasil sebenarnya, tanpa menebak output).
- Cakupan skenario positif dan negatif.

## 5. Log Hasil Pengujian

Belum ada eksekusi pengujian aplikasi pada baseline awal repository.
