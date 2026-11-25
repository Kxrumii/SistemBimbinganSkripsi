import { createApp } from './app.js';
import { loadEnv } from './config/env.js';

const HOST = '0.0.0.0';

function startServer(): void {
  const config = loadEnv();
  const app = createApp(config);

  const server = app.listen(config.apiPort, HOST, () => {
    console.log(`[sbs-api] Listening on ${HOST}:${config.apiPort} (${config.nodeEnv})`);
  });

  const shutdown = (signal: NodeJS.Signals) => {
    console.log(`[sbs-api] Received ${signal}, closing HTTP server...`);
    server.close(() => {
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10_000).unref();
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

startServer();
