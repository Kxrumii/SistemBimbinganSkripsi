FROM node:22-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
COPY client/package.json ./client/package.json
COPY server/package.json ./server/package.json

RUN npm ci --workspace=client --include-workspace-root

COPY client ./client

RUN npm run build --workspace=client

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runner

ENV API_PORT=3000 \
    NGINX_ENVSUBST_FILTER=^API_PORT$

COPY client/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=builder /app/client/dist /usr/share/nginx/html

EXPOSE 8080
