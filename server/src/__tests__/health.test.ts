import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { after, before, describe, it } from 'node:test';
import { createApp } from '../app.js';
import { loadEnv, type AppEnv } from '../config/env.js';

const TEST_CONFIG: AppEnv = {
  nodeEnv: 'test',
  apiPort: 3000,
  clientOrigin: 'http://localhost:5173',
  databaseUrl: 'postgresql://test_user:test_pass@localhost:5432/sbs_test?schema=public',
  uploadDir: './storage/revisions',
};

describe('loadEnv validation', () => {
  it('parses valid environment configuration', () => {
    const config = loadEnv({
      NODE_ENV: 'production',
      API_PORT: '4000',
      CLIENT_ORIGIN: 'https://sbs.example.test',
      DATABASE_URL: 'postgresql://u:p@db:5432/sbs',
      UPLOAD_DIR: '/app/storage/revisions',
    });

    assert.equal(config.nodeEnv, 'production');
    assert.equal(config.apiPort, 4000);
    assert.equal(config.clientOrigin, 'https://sbs.example.test');
    assert.equal(config.uploadDir, '/app/storage/revisions');
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
      const server = app.listen(0, '127.0.0.1', () => {
        const address = server.address() as AddressInfo;
        baseUrl = `http://127.0.0.1:${address.port}`;
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
