import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { after, before, describe, it } from 'node:test';
import { createApp } from '../app.js';
import { loadEnv, type AppEnv } from '../config/env.js';
import { createErrorHandler, redactSensitiveMessage } from '../middlewares/errorHandler.js';

const TEST_CONFIG: AppEnv = {
  nodeEnv: 'test',
  apiHost: '127.0.0.1',
  apiPort: 3000,
  clientOrigin: 'http://localhost:5173',
  databaseUrl: 'postgresql://test_user:test_pass@localhost:5432/sbs_test?schema=public',
  uploadDir: './storage/revisions',
};

describe('loadEnv validation', () => {
  it('parses valid environment configuration with default API_HOST 127.0.0.1', () => {
    const config = loadEnv({
      NODE_ENV: 'production',
      API_PORT: '4000',
      CLIENT_ORIGIN: 'https://sbs.example.test',
      DATABASE_URL: 'postgresql://u:p@db:5432/sbs',
      UPLOAD_DIR: '/app/storage/revisions',
    });

    assert.equal(config.nodeEnv, 'production');
    assert.equal(config.apiHost, '127.0.0.1');
    assert.equal(config.apiPort, 4000);
    assert.equal(config.clientOrigin, 'https://sbs.example.test');
    assert.equal(config.uploadDir, '/app/storage/revisions');
  });

  it('accepts explicit API_HOST for container binding and rejects invalid API_HOST', () => {
    const containerConfig = loadEnv({
      API_HOST: '0.0.0.0',
      DATABASE_URL: 'postgresql://u:p@db:5432/sbs',
      UPLOAD_DIR: '/app/storage/revisions',
    });
    assert.equal(containerConfig.apiHost, '0.0.0.0');

    assert.throws(
      () =>
        loadEnv({
          API_HOST: 'http://127.0.0.1',
          DATABASE_URL: 'postgresql://u:p@db:5432/sbs',
          UPLOAD_DIR: '/app/storage/revisions',
        }),
      /API_HOST must be a valid bind IP or hostname/,
    );
  });

  it('rejects missing DATABASE_URL without leaking secrets', () => {
    assert.throws(
      () =>
        loadEnv({
          NODE_ENV: 'development',
          API_PORT: '3000',
          CLIENT_ORIGIN: 'http://localhost:5173',
          UPLOAD_DIR: './storage/revisions',
        }),
      /DATABASE_URL is required/,
    );
  });

  it('rejects wildcard CLIENT_ORIGIN and invalid API_PORT', () => {
    assert.throws(
      () =>
        loadEnv({
          API_PORT: '99999',
          CLIENT_ORIGIN: '*',
          DATABASE_URL: 'postgresql://u:p@db:5432/sbs',
          UPLOAD_DIR: './storage/revisions',
        }),
      /API_PORT.*CLIENT_ORIGIN/,
    );
  });
});

describe('Express API foundation', () => {
  let baseUrl = '';
  let closeServer: () => Promise<void>;

  before(async () => {
    const app = createApp(TEST_CONFIG);
    await new Promise<void>((resolve) => {
      const server = app.listen(0, TEST_CONFIG.apiHost, () => {
        const address = server.address() as AddressInfo;
        assert.equal(address.address, '127.0.0.1');
        baseUrl = `http://${address.address}:${address.port}`;
        closeServer = () =>
          new Promise<void>((done, fail) => {
            server.close((err) => (err ? fail(err) : done()));
          });
        resolve();
      });
    });
  });

  after(async () => {
    if (closeServer) {
      await closeServer();
    }
  });

  it('GET /api/v1/health returns safe 200 payload', async () => {
    const res = await fetch(`${baseUrl}/api/v1/health`);
    assert.equal(res.status, 200);
    const body = (await res.json()) as {
      success: boolean;
      message: string;
      data: { status: string; service: string; timestamp: string };
    };

    assert.equal(body.success, true);
    assert.equal(body.data.status, 'ok');
    assert.equal(body.data.service, 'sbs-api');
    assert.ok(!Number.isNaN(Date.parse(body.data.timestamp)));

    const serialized = JSON.stringify(body);
    assert.equal(serialized.includes('test_pass'), false);
    assert.equal(serialized.includes('storage/revisions'), false);
    assert.equal(serialized.includes('postgresql://'), false);
  });

  it('returns 404 JSON on unknown API route', async () => {
    const res = await fetch(`${baseUrl}/api/v1/does-not-exist`);
    assert.equal(res.status, 404);
    const body = (await res.json()) as { success: boolean; error: { code: string } };
    assert.equal(body.success, false);
    assert.equal(body.error.code, 'NOT_FOUND');
  });

  it('returns 400 JSON on malformed JSON request body', async () => {
    const res = await fetch(`${baseUrl}/api/v1/health`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"broken": ',
    });
    assert.equal(res.status, 400);
    const body = (await res.json()) as { success: boolean; error: { code: string } };
    assert.equal(body.success, false);
    assert.equal(body.error.code, 'INVALID_JSON');
  });
});

describe('Error logging safeguards', () => {
  it('redacts connection strings, bearer tokens, and secrets', () => {
    const raw =
      'Failed connecting postgresql://u:SuperSecret99@db:5432/sbs with Bearer tok123 and password=my_pw';
    const safe = redactSensitiveMessage(raw);
    assert.equal(safe.includes('SuperSecret99'), false);
    assert.equal(safe.includes('tok123'), false);
    assert.equal(safe.includes('my_pw'), false);
    assert.ok(safe.includes('[REDACTED]'));
  });

  it('keeps production 500 responses and logs free of raw error messages or secrets', () => {
    const logs: unknown[][] = [];
    const origError = console.error;
    console.error = (...args: unknown[]) => {
      logs.push(args);
    };

    try {
      let capturedStatus = 0;
      let capturedBody: unknown = null;
      const fakeRes = {
        status(code: number) {
          capturedStatus = code;
          return this;
        },
        json(payload: unknown) {
          capturedBody = payload;
        },
      };
      const fakeReq = { method: 'GET', path: '/api/v1/health' };
      const handler = createErrorHandler('production');
      handler(
        new Error('Connect failed: postgresql://sbs_user:SuperSecret99@db:5432/sbs'),
        fakeReq as never,
        fakeRes as never,
        (() => {}) as never,
      );

      assert.equal(capturedStatus, 500);
      assert.deepEqual(capturedBody, {
        success: false,
        error: {
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Terjadi kesalahan internal pada server',
        },
      });
      const serializedLogs = JSON.stringify(logs);
      assert.equal(serializedLogs.includes('SuperSecret99'), false);
      assert.equal(serializedLogs.includes('Connect failed'), false);
      assert.equal(serializedLogs.includes('postgresql://'), false);
    } finally {
      console.error = origError;
    }
  });

  it('redacts sensitive details in development error logs', () => {
    const logs: unknown[][] = [];
    const origError = console.error;
    console.error = (...args: unknown[]) => {
      logs.push(args);
    };

    try {
      const fakeRes = {
        status() {
          return this;
        },
        json() {},
      };
      const fakeReq = { method: 'POST', path: '/api/v1/test' };
      const handler = createErrorHandler('development');
      handler(
        new Error('Database error at postgresql://sbs_user:SuperSecret99@db:5432/sbs'),
        fakeReq as never,
        fakeRes as never,
        (() => {}) as never,
      );

      const serializedLogs = JSON.stringify(logs);
      assert.equal(serializedLogs.includes('SuperSecret99'), false);
      assert.ok(serializedLogs.includes('[REDACTED]'));
    } finally {
      console.error = origError;
    }
  });
});
