# Infrastruktur & Kontainer (`infra/`)

Direktori ini disiapkan untuk artefak konfigurasi infrastruktur dan operasional deployment (`SBS-14` dan `SBS-15`).

## Batas Jaringan & Runtime Kontainer (`SBS-04`)

- **`web` (`client/Dockerfile`):** Menjalankan Nginx non-root (`nginxinc/nginx-unprivileged:1.27-alpine`) pada port kontainer `8080`, melayani static build React/Vite, dan mem-proxy `/api/` ke `http://api:${API_PORT}`. Hanya service `web` yang di-bind ke host melalui loopback (`${WEB_BIND_ADDRESS:-127.0.0.1}:${WEB_PORT:-8080}:8080`).
- **`api` (`server/Dockerfile`):** Menjalankan Express.js + TypeScript sebagai user non-root `node` hanya pada jaringan `internal`, dengan volume privat `sbs_uploads` pada `/app/storage/revisions`.
- **`db` (`postgres:16-alpine`):** Berjalan hanya pada jaringan `internal` dengan named volume `sbs_pgdata`.

Konfigurasi reverse proxy eksternal, HTTPS, domain `sbs.kxrumii.my.id`, serta backup/restore dijadwalkan pada `SBS-14` dan `SBS-15`.
