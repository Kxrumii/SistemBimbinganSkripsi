import type { ErrorRequestHandler } from 'express';
import type { NodeEnv } from '../config/env.js';
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

/**
 * Masks credentials, database URLs, and bearer tokens before emitting diagnostic logs.
 */
export function redactSensitiveMessage(message: string): string {
  return message
    .replace(/postgres(?:ql)?:\/\/[^\s'"]+/gi, 'postgresql://[REDACTED]')
    .replace(/(bearer\s+)[a-zA-Z0-9._~+/-]+=*/gi, '$1[REDACTED]')
    .replace(
      /\b(password|passwd|secret|token|jwt_secret|database_url)\s*([:=])\s*[^\s,;]+/gi,
      '$1$2[REDACTED]',
    );
}

export function createErrorHandler(nodeEnv: NodeEnv): ErrorRequestHandler {
  return (err, req, res, _next) => {
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

    const errorName = err instanceof Error ? err.name : 'UnknownError';
    if (nodeEnv === 'development') {
      const safeMessage = err instanceof Error ? redactSensitiveMessage(err.message) : 'Unknown error';
      console.error('[sbs-api] Unhandled server error', {
        errorName,
        method: req.method,
        path: req.path,
        message: safeMessage,
      });
    } else {
      console.error('[sbs-api] Unhandled server error', {
        errorName,
        method: req.method,
        path: req.path,
      });
    }

    res.status(500).json({
      success: false,
      error: {
        code: 'INTERNAL_SERVER_ERROR',
        message: 'Terjadi kesalahan internal pada server',
      },
    });
  };
}
