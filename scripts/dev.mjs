import { spawn } from 'node:child_process';

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const processes = [];
let shuttingDown = false;

function startWorkspace(name, workspace) {
  const child = spawn(npmCmd, ['run', 'dev', `--workspace=${workspace}`], {
    stdio: 'inherit',
    env: process.env,
  });

  child.on('exit', (code, signal) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    const exitCode = code ?? (signal ? 1 : 0);
    if (exitCode !== 0) {
      console.error(`[dev] Workspace "${name}" berhenti (code=${code ?? 'null'}, signal=${signal ?? 'none'}).`);
    }
    for (const proc of processes) {
      if (proc !== child && !proc.killed) {
        proc.kill('SIGTERM');
      }
    }
    process.exit(exitCode);
  });

  processes.push(child);
}

function shutdown(signal) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const proc of processes) {
    if (!proc.killed) {
      proc.kill(signal);
    }
  }
  setTimeout(() => process.exit(0), 250).unref();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

startWorkspace('server', 'server');
startWorkspace('client', 'client');
