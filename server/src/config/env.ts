import path from 'node:path';
import { fileURLToPath } from 'node:url';
import dotenv from 'dotenv';

export type NodeEnv = 'development' | 'test' | 'production';

export interface AppEnv {
  nodeEnv: NodeEnv;
  apiHost: string;
  apiPort: number;
  clientOrigin: string;
  databaseUrl: string;
  uploadDir: string;
}

const VALID_NODE_ENVS = new Set<NodeEnv>(['development', 'test', 'production']);

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const rootEnvPath = path.resolve(currentDir, '../../../.env');

dotenv.config({ path: rootEnvPath });

function parseNodeEnv(rawValue: string | undefined): NodeEnv {
  const value = (rawValue ?? 'development').trim();
  if (!VALID_NODE_ENVS.has(value as NodeEnv)) {
    throw new Error('NODE_ENV must be one of development, test, or production');
  }
  return value as NodeEnv;
}

function parseApiHost(rawValue: string | undefined): string {
  const value = (rawValue ?? '127.0.0.1').trim();
  if (!value || value === '*' || value.includes('://') || !/^[a-zA-Z0-9.:-]+$/.test(value)) {
    throw new Error('API_HOST must be a valid bind IP or hostname without scheme or whitespace');
  }
  return value;
}

function parsePort(rawValue: string | undefined): number {
  const value = (rawValue ?? '3000').trim();
  if (!/^\d+$/.test(value)) {
    throw new Error('API_PORT must be an integer between 1 and 65535');
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('API_PORT must be an integer between 1 and 65535');
  }
  return port;
}

function parseClientOrigin(rawValue: string | undefined): string {
  const value = (rawValue ?? 'http://localhost:5173').trim();
  if (!value || value === '*' || value.includes('*')) {
    throw new Error('CLIENT_ORIGIN must be an explicit http(s) origin without wildcards');
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('CLIENT_ORIGIN must be a valid http(s) URL');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('CLIENT_ORIGIN must use http or https protocol');
  }
  return parsed.origin;
}

function parseDatabaseUrl(rawValue: string | undefined): string {
  const value = rawValue?.trim() ?? '';
  if (!value) {
    throw new Error('DATABASE_URL is required');
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error('DATABASE_URL must be a valid PostgreSQL connection URL');
  }
  if (parsed.protocol !== 'postgres:' && parsed.protocol !== 'postgresql:') {
    throw new Error('DATABASE_URL must use postgres:// or postgresql:// scheme');
  }
  return value;
}

function parseUploadDir(rawValue: string | undefined): string {
  const value = rawValue?.trim() ?? '';
  if (!value) {
    throw new Error('UPLOAD_DIR is required');
  }
  return value;
}

/**
 * Validates required startup environment variables without exposing secret values.
 */
export function loadEnv(envSource: NodeJS.ProcessEnv = process.env): AppEnv {
  const errors: string[] = [];

  const capture = <T>(fn: () => T): T | undefined => {
    try {
      return fn();
    } catch (error) {
      errors.push(error instanceof Error ? error.message : 'Invalid environment configuration');
      return undefined;
    }
  };

  const nodeEnv = capture(() => parseNodeEnv(envSource.NODE_ENV));
  const apiHost = capture(() => parseApiHost(envSource.API_HOST));
  const apiPort = capture(() => parsePort(envSource.API_PORT));
  const clientOrigin = capture(() => parseClientOrigin(envSource.CLIENT_ORIGIN));
  const databaseUrl = capture(() => parseDatabaseUrl(envSource.DATABASE_URL));
  const uploadDir = capture(() => parseUploadDir(envSource.UPLOAD_DIR));

  if (
    errors.length > 0 ||
    !nodeEnv ||
    !apiHost ||
    !apiPort ||
    !clientOrigin ||
    !databaseUrl ||
    !uploadDir
  ) {
    throw new Error(`Invalid startup environment configuration: ${errors.join('; ')}`);
  }

  return {
    nodeEnv,
    apiHost,
    apiPort,
    clientOrigin,
    databaseUrl,
    uploadDir,
  };
}
