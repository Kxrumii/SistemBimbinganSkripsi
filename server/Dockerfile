FROM node:22-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
COPY client/package.json ./client/package.json
COPY server/package.json ./server/package.json

RUN npm ci --workspace=server --include-workspace-root

COPY server ./server

RUN npm run build --workspace=server

FROM node:22-slim AS prod-deps

WORKDIR /app

COPY package.json package-lock.json ./
COPY client/package.json ./client/package.json
COPY server/package.json ./server/package.json

RUN npm ci --omit=dev --workspace=server --include-workspace-root && \
    mkdir -p /app/server/node_modules

FROM node:22-slim AS runner

WORKDIR /app

ENV NODE_ENV=production

RUN mkdir -p /app/storage/revisions && \
    chown -R node:node /app

COPY --chown=node:node --from=prod-deps /app/node_modules ./node_modules
COPY --chown=node:node --from=prod-deps /app/server/node_modules ./server/node_modules
COPY --chown=node:node package.json ./package.json
COPY --chown=node:node server/package.json ./server/package.json
COPY --chown=node:node --from=builder /app/server/dist ./server/dist

USER node

EXPOSE 3000

CMD ["node", "server/dist/server.js"]
