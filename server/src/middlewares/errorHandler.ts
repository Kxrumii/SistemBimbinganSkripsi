import type { ErrorRequestHandler } from 'express';
import { AppError } from '../utils/appError.js';

interface BodyParserSyntaxError extends SyntaxError {
  status?: number;
  body?: unknown;
}

function isInvalidJsonError(err: unknown): err is BodyParserSyntaxError {
  return (
    err instanceof SyntaxError &&
    typeof (err as BodyParserSyntaxError).status === 'number' &&
    (err as BodyParserSyntaxError).status === 400 &&
    'body' in err
  );
}

export const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
  if (isInvalidJsonError(err)) {
    res.status(400).json({
      success: false,
      error: {
        code: 'INVALID_JSON',
        message: 'Format JSON pada body request tidak valid',
      },
    });
    return;
  }

  if (err instanceof AppError) {
    res.status(err.statusCode).json({
      success: false,
      error: {
        code: err.code,
        message: err.message,
      },
    });
    return;
  }

  console.error('[sbs-api] Unhandled server error:', err instanceof Error ? err.message : 'Unknown error');

  res.status(500).json({
    success: false,
    error: {
      code: 'INTERNAL_SERVER_ERROR',
      message: 'Terjadi kesalahan internal pada server',
    },
  });
};
