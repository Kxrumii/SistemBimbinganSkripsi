import { useCallback, useEffect, useState } from 'react';
import { API_BASE_PATH, fetchHealth, type HealthStatusData } from './lib/apiClient';

type HealthCheckState =
  | { status: 'loading' }
  | { status: 'ok'; data: HealthStatusData; message: string }
  | { status: 'error'; errorMessage: string };

const FOUNDATION_MODULES = [
  {
    title: 'Frontend (client/)',
    detail: 'React, Vite, TypeScript, Tailwind CSS dengan proxy dev dan API client di /api/v1.',
    owner: 'Diperluas pada SBS-12 dan paket fitur',
  },
  {
    title: 'Backend (server/)',
    detail: 'Express.js, TypeScript, validasi environment startup, error handling, dan /api/v1/health.',
    owner: 'Diperluas pada SBS-05 s.d. SBS-11',
  },
  {
    title: 'Database & Volume',
    detail: 'PostgreSQL 16 pada internal Docker network beserta volume data dan upload privat.',
    owner: 'Schema Prisma & migrasi disiapkan pada SBS-19',
  },
];

export function App() {
  const [health, setHealth] = useState<HealthCheckState>({ status: 'loading' });

  const checkHealth = useCallback(async (signal?: AbortSignal) => {
    setHealth({ status: 'loading' });
    try {
      const response = await fetchHealth(signal);
      if (signal?.aborted) {
        return;
      }
      setHealth({
        status: 'ok',
        data: response.data,
        message: response.message,
      });
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      const errorMessage =
        error instanceof Error ? error.message : 'Gagal terhubung ke layanan API backend.';
      setHealth({ status: 'error', errorMessage });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal);
    return () => controller.abort();
  }, [checkHealth]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-col gap-2 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div>
            <p className="text-xs font-semibold tracking-wider text-slate-500 uppercase">
              Kelompok A4 · SBS-04
            </p>
            <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
              Sistem Bimbingan Skripsi
            </h1>
          </div>
          <span className="inline-flex w-fit items-center rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
            Fondasi Aplikasi &amp; Containerization
          </span>
        </div>
      </header>

      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8 sm:px-6">
        <section
          aria-labelledby="health-heading"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs sm:p-6"
        >
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="health-heading" className="text-base font-semibold text-slate-900">
                Status Konektivitas API
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                Memeriksa endpoint{' '}
                <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800">
                  GET {API_BASE_PATH}/health
                </code>{' '}
                melalui origin aplikasi yang sama.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void checkHealth()}
              className="inline-flex w-fit items-center justify-center rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 focus:ring-2 focus:ring-slate-400 focus:outline-none"
            >
              Periksa Ulang
            </button>
          </div>

          <div
            aria-live="polite"
            className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm"
          >
            {health.status === 'loading' && (
              <p className="text-slate-600">Memeriksa ketersediaan backend API...</p>
            )}

            {health.status === 'ok' && (
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="h-2.5 w-2.5 rounded-full bg-emerald-600"
                  />
                  <span className="font-semibold text-emerald-800">
                    Terhubung ({health.data.service}: {health.data.status})
                  </span>
                </div>
                <p className="text-slate-600">{health.message}</p>
                <p className="text-xs text-slate-500">
                  Timestamp server: {health.data.timestamp}
                </p>
              </div>
            )}

            {health.status === 'error' && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-rose-600" />
                  <span className="font-semibold text-rose-800">API belum terjangkau</span>
                </div>
                <p className="text-slate-700">{health.errorMessage}</p>
              </div>
            )}
          </div>
        </section>

        <section aria-labelledby="modules-heading" className="flex flex-col gap-3">
          <h2 id="modules-heading" className="text-base font-semibold text-slate-900">
            Struktur Fondasi Repository
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {FOUNDATION_MODULES.map((item) => (
              <article
                key={item.title}
                className="flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-xs"
              >
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{item.detail}</p>
                </div>
                <p className="mt-4 border-t border-slate-100 pt-2.5 text-xs text-slate-500">
                  {item.owner}
                </p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
