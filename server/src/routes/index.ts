import { Router } from 'express';
import { healthRouter } from './health.route.js';

export const apiRouter = Router();

apiRouter.use('/health', healthRouter);

// Feature module routers (SBS-05 s.d. SBS-11) akan dipasang di bawah prefix /api/v1.
