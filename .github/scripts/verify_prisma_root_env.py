#!/usr/bin/env python3
"""Isolated runtime verification proving Prisma 7.10.1 loads root .env from npm workspace server without cwd fallback or override."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PRISMA_VERSION = "7.10.1"
PRISMA_CLIENT_VERSION = "7.10.1"
DOTENV_VERSION = "16.6.1"

SCRIPT_DIR = Path(__file__).resolve().parent
FIXTURE_CONFIG_PATH = SCRIPT_DIR.parent / "fixtures/prisma7.config.ts"
REPO_ROOT = SCRIPT_DIR.parent.parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_db_contract as v  # noqa: E402


FAKE_ROOT_DB_URL = "postgresql://fixture_user:fixture_pass@127.0.0.1:59999/fixture_db?schema=public"
FAKE_CI_DB_URL = "postgresql://ci_user:ci_pass@127.0.0.1:59998/ci_db?schema=public"
INVALID_ENV_SENTINEL = "invalid-sentinel-not-postgres"

SCHEMA_PRISMA = """generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
}

model User {
  id String @id
}
"""


def redact_sensitive(text: str) -> str:
    redacted = re.sub(r"postgres(?:ql)?://[^\s\"'`]+", "postgresql://<REDACTED>", text)
    return redacted.replace(INVALID_ENV_SENTINEL, "<REDACTED_SENTINEL>")


def build_clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, val in os.environ.items():
        if key == "DATABASE_URL" or key.startswith("DOTENV_"):
            continue
        cleaned[key] = val
    cleaned["PRISMA_HIDE_UPDATE_MESSAGE"] = "1"
    cleaned["CHECKPOINT_DISABLE"] = "1"
    if extra:
        cleaned.update(extra)
    return cleaned


def run_workspace_script(
    npm_bin: str,
    fixture_root: Path,
    script_name: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    res = subprocess.run(
        [npm_bin, "run", script_name, "--workspace=server"],
        cwd=fixture_root,
        env=build_clean_env(extra_env),
        text=True,
        capture_output=True,
        check=False,
    )
    combined = "\n".join(part for part in (res.stdout, res.stderr) if part)
    return res.returncode, combined


def resolve_installed_pkg_version(fixture_root: Path, pkg_name: str) -> str:
    nested = fixture_root / "server/node_modules" / pkg_name / "package.json"
    hoisted = fixture_root / "node_modules" / pkg_name / "package.json"
    target = nested if nested.is_file() else hoisted
    if not target.is_file():
        raise AssertionError(f"Installed package '{pkg_name}' missing inside temporary fixture")
    data = json.loads(target.read_text(encoding="utf-8"))
    return str(data.get("version", ""))


def main() -> int:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        print("::error::npm binary is required for Prisma runtime root .env verification")
        return 1

    if not FIXTURE_CONFIG_PATH.is_file():
        print(f"::error::Canonical config fixture missing: {FIXTURE_CONFIG_PATH}")
        return 1

    canonical_config = FIXTURE_CONFIG_PATH.read_text(encoding="utf-8")
    parser_errors = v.validate_canonical_prisma_config_content(canonical_config)
    if parser_errors:
        for err in parser_errors:
            print(f"::error::{err}")
        return 1

    results: list[tuple[str, str, str]] = []

    with tempfile.TemporaryDirectory(prefix="sbs-prisma7-env-") as tmp:
        root = Path(tmp)
        (root / "server/prisma/migrations/20261126000000_init").mkdir(parents=True, exist_ok=True)

        (root / "package.json").write_text(
            json.dumps({"name": "sbs-runtime-env-probe", "private": True, "workspaces": ["server"]}, indent=2),
            encoding="utf-8",
        )
        (root / "server/package.json").write_text(
            json.dumps(
                {
                    "name": "sbs-server-runtime-probe",
                    "private": True,
                    "type": "module",
                    "scripts": {
                        "db:validate": "prisma validate --schema=prisma/schema.prisma",
                        "db:migrate:deploy": "prisma migrate deploy --schema=prisma/schema.prisma",
                    },
                    "dependencies": {
                        "@prisma/client": PRISMA_CLIENT_VERSION,
                        "dotenv": DOTENV_VERSION,
                    },
                    "devDependencies": {
                        "prisma": PRISMA_VERSION,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "server/prisma7.config.ts").write_text(canonical_config, encoding="utf-8")
        (root / "server/prisma/schema.prisma").write_text(SCHEMA_PRISMA, encoding="utf-8")
        (root / "server/prisma/migrations/migration_lock.toml").write_text(
            'provider = "postgresql"\n', encoding="utf-8"
        )
        (root / "server/prisma/migrations/20261126000000_init/migration.sql").write_text(
            "CREATE TABLE users (id TEXT PRIMARY KEY);\n", encoding="utf-8"
        )

        install = subprocess.run(
            [npm_bin, "install", "--no-audit", "--no-fund"],
            cwd=root,
            env=build_clean_env(),
            text=True,
            capture_output=True,
            check=False,
        )
        if install.returncode != 0:
            print(f"::error::npm install in temporary fixture failed:\n{redact_sensitive(install.stderr or install.stdout)}")
            return 1

        installed_versions = {
            pkg: resolve_installed_pkg_version(root, pkg)
            for pkg in ("prisma", "@prisma/client", "dotenv")
        }
        expected_versions = {
            "prisma": PRISMA_VERSION,
            "@prisma/client": PRISMA_CLIENT_VERSION,
            "dotenv": DOTENV_VERSION,
        }
        if installed_versions != expected_versions:
            print(
                f"::error::Temporary fixture resolved unexpected package versions: {installed_versions} != {expected_versions}"
            )
            return 1

        root_env = root / ".env"
        server_env = root / "server/.env"

        # Scenario 1: Root .env present, process env clean, server/.env absent
        root_env.write_text(f'DATABASE_URL="{FAKE_ROOT_DB_URL}"\n', encoding="utf-8")
        assert not server_env.exists()

        val_code, val_out = run_workspace_script(npm_bin, root, "db:validate")
        if val_code != 0 or "Loaded Prisma config from prisma7.config.ts." not in val_out:
            print(f"::error::Scenario 1 db:validate failed (exit={val_code}):\n{redact_sensitive(val_out)}")
            return 1

        mig_code, mig_out = run_workspace_script(npm_bin, root, "db:migrate:deploy")
        if (
            "Loaded Prisma config from prisma7.config.ts." not in mig_out
            or 'PostgreSQL database "fixture_db", schema "public" at "127.0.0.1:59999"' not in mig_out
            or "The datasource.url property is required" in mig_out
            or "P1001" not in mig_out
        ):
            print(
                f"::error::Scenario 1 failed to load root .env into Prisma CLI (exit={mig_code}):\n{redact_sensitive(mig_out)}"
            )
            return 1
        results.append(
            (
                "Root .env present, process env clean, no server/.env",
                "PASS",
                "db:validate exited 0; db:migrate:deploy resolved root .env datasource without server/.env",
            )
        )

        # Scenario 2: Missing root .env, missing server/.env, clean process env
        root_env.unlink()
        assert not root_env.exists() and not server_env.exists()

        s2_code, s2_out = run_workspace_script(npm_bin, root, "db:migrate:deploy")
        if s2_code == 0 or "The datasource.url property is required" not in s2_out:
            print(
                f"::error::Scenario 2 expected missing datasource.url failure (exit={s2_code}):\n{redact_sensitive(s2_out)}"
            )
            return 1
        results.append(
            (
                "Missing root .env and missing server/.env",
                "PASS (FAIL as expected)",
                "CLI rejected missing datasource.url when no .env or process env was provided",
            )
        )

        # Scenario 3: Missing root .env, only server/.env exists (must NOT fallback)
        server_env.write_text(f'DATABASE_URL="{FAKE_ROOT_DB_URL}"\n', encoding="utf-8")
        s3_code, s3_out = run_workspace_script(npm_bin, root, "db:migrate:deploy")
        server_env.unlink()
        if s3_code == 0 or "The datasource.url property is required" not in s3_out:
            print(
                f"::error::Scenario 3 expected server/.env NOT to act as fallback (exit={s3_code}):\n{redact_sensitive(s3_out)}"
            )
            return 1
        results.append(
            (
                "Missing root .env, only server/.env present",
                "PASS (FAIL as expected)",
                "CLI did not fallback to server/.env; datasource.url remained unset",
            )
        )

        # Scenario 4: Valid root .env + invalid sentinel DATABASE_URL in process env (override: false)
        root_env.write_text(f'DATABASE_URL="{FAKE_ROOT_DB_URL}"\n', encoding="utf-8")
        s4_code, s4_out = run_workspace_script(
            npm_bin,
            root,
            "db:migrate:deploy",
            extra_env={"DATABASE_URL": INVALID_ENV_SENTINEL},
        )
        if (
            s4_code == 0
            or "P1013" not in s4_out
            or "The provided database string is invalid" not in s4_out
        ):
            print(
                f"::error::Scenario 4 expected process env precedence P1013 failure (exit={s4_code}):\n{redact_sensitive(s4_out)}"
            )
            return 1
        results.append(
            (
                "Root .env valid + invalid process env sentinel",
                "PASS (FAIL as expected)",
                "Process env took precedence over root .env (override: false; P1013)",
            )
        )

        # Scenario 5: No .env files + valid CI process env DATABASE_URL
        root_env.unlink()
        assert not root_env.exists() and not server_env.exists()
        s5_val_code, s5_val_out = run_workspace_script(
            npm_bin,
            root,
            "db:validate",
            extra_env={"DATABASE_URL": FAKE_CI_DB_URL},
        )
        s5_mig_code, s5_mig_out = run_workspace_script(
            npm_bin,
            root,
            "db:migrate:deploy",
            extra_env={"DATABASE_URL": FAKE_CI_DB_URL},
        )
        if (
            s5_val_code != 0
            or "The schema at prisma/schema.prisma is valid" not in s5_val_out
            or 'PostgreSQL database "ci_db", schema "public" at "127.0.0.1:59998"' not in s5_mig_out
            or "P1001" not in s5_mig_out
        ):
            print(
                f"::error::Scenario 5 CI process env mode failed (val={s5_val_code}, mig={s5_mig_code}):\n{redact_sensitive(s5_mig_out)}"
            )
            return 1
        results.append(
            (
                "No .env files + valid CI process env",
                "PASS",
                "db:validate exited 0 and CLI read process DATABASE_URL without failing on absent .env",
            )
        )

    print(
        "Verified isolated Prisma runtime root .env loading "
        f"(prisma={installed_versions['prisma']}, @prisma/client={installed_versions['@prisma/client']}, "
        f"dotenv={installed_versions['dotenv']}):"
    )
    for scenario, status, detail in results:
        print(f"- [{status}] {scenario}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
