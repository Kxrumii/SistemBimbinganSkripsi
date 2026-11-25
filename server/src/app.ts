import cors from 'cors';
import express from 'express';
import helmet from 'helmet';
import type { AppEnv } from './config/env.js';
import { errorHandler } from './middlewares/errorHandler.js';
import { notFoundHandler } from './middlewares/notFound.js';
import { apiRouter } from './routes/index.js';

/**
 * Creates the configured Express application without binding a network port.
 */
export function createApp(config: AppEnv): express.Express {
  const app = express();

  app.disable('x-powered-by');
  app.set('trust proxy', 1);

  app.use(helmet());
  app.use(
    cors({
      origin: config.clientOrigin,
      credentials: true,
    }),
  );
  app.use(express.json({ limit: '1mb' }));

  app.use('/api/v1', apiRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
