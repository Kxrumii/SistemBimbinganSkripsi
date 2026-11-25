import { Router } from 'express';

export const healthRouter = Router();

healthRouter.get('/', (_req, res) => {
  res.status(200).json({
    success: true,
    message: 'Layanan API berjalan normal',
    data: {
      status: 'ok',
      service: 'sbs-api',
      timestamp: new Date().toISOString(),
    },
  });
});
