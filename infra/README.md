# Infrastruktur & Kontainer (`infra/`)

Direktori ini disiapkan untuk konfigurasi infrastruktur dan operasional deployment (`SBS-14` dan `SBS-15`).

## Kontrak Jaringan & Runtime Kontainer (`SBS-04`)

- **`web` (`client/Dockerfile`):**
  - Base image `nginxinc/nginx-unprivileged:1.30.6-alpine`, berjalan non-root (`uid=101(nginx)`) pada port kontainer `8080`.
  - Menyajikan static build React/Vite (`/`), readiness probe (`/healthz`), dan mem-proxy `/api/` ke `http://api:${API_PORT}`.
  - Scope `location /api/` menetapkan `client_max_body_size 12m;` sebagai headroom multipart overhead untuk batas bisnis 10 MiB (`10.485.760` byte) yang divalidasi backend (`SBS-09` / ADR-011).
  - Pada `compose.yaml` utama, hanya `web` yang di-bind ke host melalui loopback (`${WEB_BIND_ADDRESS:-127.0.0.1}:${WEB_PORT:-8080}:8080`).
- **`api` (`server/Dockerfile`):**
  - Base image `node:22-slim`, berjalan non-root (`uid=1000(node)`), terisolasi pada jaringan `internal` (`internal: true`) tanpa port host.
  - Di dalam `compose.yaml`, `API_HOST` di-set ke `0.0.0.0` (sementara development lokal pada host memakai `127.0.0.1`).
  - Volume privat `sbs_uploads` hanya dipasang pada `api` di `/app/storage/revisions` dan tidak disajikan sebagai static path pada `web`.
- **`db` (`postgres:16-alpine`):**
  - Pada `compose.yaml` utama, hanya berada pada jaringan `internal` dengan named volume `sbs_pgdata` dan tanpa port host.
  - Akses host `127.0.0.1:5432` hanya tersedia melalui override development lokal `compose.dev.yaml`.

Konfigurasi reverse proxy server produksi, domain `https://sbs.kxrumii.my.id`, HTTPS/Cloudflare Tunnel, serta backup/restore dijadwalkan pada `SBS-14` dan `SBS-15`. Identitas host internal tidak dicantumkan di repository sesuai ADR-012.
