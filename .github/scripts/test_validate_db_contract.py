#!/usr/bin/env python3
"""Unit and regression tests for .github/scripts/validate_db_contract.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_db_contract as v  # noqa: E402


FIXTURE_CONFIG_PATH = SCRIPT_DIR.parent / "fixtures/prisma7.config.ts"
CANONICAL_CONFIG_CONTENT = FIXTURE_CONFIG_PATH.read_text(encoding="utf-8")

VALID_SCRIPTS = {
    "db:validate": "prisma validate --schema=prisma/schema.prisma",
    "db:migrate:deploy": "prisma migrate deploy --schema=prisma/schema.prisma",
    "db:seed": "tsx prisma/seed.ts",
    "test:db": "node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
}


class TempRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._git(["init", "-q"])
        self._git(["config", "user.email", "ci@example.test"])
        self._git(["config", "user.name", "CI Test"])
        self.write_file("README.md", "# Test repo\n")
        self.write_file(
            "package.json",
            json.dumps({"name": "test-root", "private": True, "workspaces": ["server"]}, indent=2),
        )
        self.write_file(
            "package-lock.json",
            json.dumps({"name": "test-root", "lockfileVersion": 3, "packages": {"": {"name": "test-root"}}}, indent=2),
        )
        self.base_sha = self.commit_all("initial")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _git(self, args: list[str]) -> str:
        res = subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        return res.stdout.strip()

    def write_file(self, rel_path: str, content: str) -> None:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit_all(self, msg: str) -> str:
        self._git(["add", "-A"])
        self._git(["commit", "-q", "-m", msg])
        return self._git(["rev-parse", "HEAD"])

    def write_valid_sbs19_contract(
        self,
        overrides: dict[str, str] | None = None,
        prisma_cfg: object | None = None,
        *,
        prisma_cli_version: str = "7.10.1",
        prisma_client_version: str = "7.10.1",
        lock_cli_version: str = "7.10.1",
        lock_client_version: str = "7.10.1",
        nested_lock: bool = False,
        config_content: str = CANONICAL_CONFIG_CONTENT,
    ) -> None:
        self.write_file(
            "package.json",
            json.dumps({"name": "test-root", "private": True, "workspaces": ["server"]}, indent=2),
        )
        self.write_file("server/prisma7.config.ts", config_content)
        self.write_file("server/prisma/schema.prisma", 'datasource db {\n  provider = "postgresql"\n}\n')
        self.write_file(
            "server/prisma/migrations/migration_lock.toml",
            '# Prisma migration lock\nprovider = "postgresql"\n',
        )
        self.write_file(
            "server/prisma/migrations/20261126000000_init/migration.sql",
            "CREATE TABLE users (id TEXT PRIMARY KEY);\n",
        )
        self.write_file("server/prisma/seed.ts", "async function main() {}\nmain();\n")
        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            'import test from "node:test";\nimport assert from "node:assert/strict";\n'
            'test("enforces unique constraint", () => { assert.equal(1, 1); });\n',
        )
        scripts = dict(VALID_SCRIPTS)
        if overrides:
            scripts.update(overrides)
        pkg_obj: dict[str, object] = {
            "name": "sbs-server",
            "dependencies": {"@prisma/client": prisma_client_version},
            "devDependencies": {"prisma": prisma_cli_version},
            "scripts": scripts,
        }
        if prisma_cfg is not None:
            pkg_obj["prisma"] = prisma_cfg
        self.write_file("server/package.json", json.dumps(pkg_obj, indent=2))

        cli_key = "server/node_modules/prisma" if nested_lock else "node_modules/prisma"
        client_key = "server/node_modules/@prisma/client" if nested_lock else "node_modules/@prisma/client"
        lock_obj = {
            "name": "test-root",
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "test-root", "workspaces": ["server"]},
                "server": {
                    "name": "sbs-server",
                    "dependencies": {"@prisma/client": prisma_client_version},
                    "devDependencies": {"prisma": prisma_cli_version},
                },
                cli_key: {"version": lock_cli_version},
                client_key: {"version": lock_client_version},
            },
        }
        self.write_file("package-lock.json", json.dumps(lock_obj, indent=2))

    def run_check(
        self, event_name: str = "pull_request", base_sha: str | None = None
    ) -> tuple[int, str, str]:
        gh_out = self.root / ".gh_out"
        gh_out.write_text("", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = v.main(
                [
                    "check-schema-and-contract",
                    "--repo-root",
                    str(self.root),
                    "--event-name",
                    event_name,
                    "--base-sha",
                    base_sha if base_sha is not None else self.base_sha,
                    "--github-output",
                    str(gh_out),
                ]
            )
        return code, gh_out.read_text(encoding="utf-8"), buf.getvalue()

    def run_runtime_version_check(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = v.main(["verify-runtime-versions", "--repo-root", str(self.root)])
        return code, buf.getvalue()


class DatabaseContractValidatorTests(TempRepoTestCase):
    def test_pre_sbs19_baseline_returns_na_and_passes(self) -> None:
        self.write_file(
            "server/package.json",
            json.dumps({"scripts": {"test": "tsx --test src/__tests__/*.test.ts"}}),
        )
        code, gh_out, logs = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("run_prisma=false", gh_out)
        self.assertIn("N/A", logs)

    def test_rejects_partial_sbs19_artifacts_without_returning_na(self) -> None:
        # 1. Canonical config exists without schema
        self.write_file("server/prisma7.config.ts", CANONICAL_CONFIG_CONTENT)
        code, gh_out, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("run_prisma=false", gh_out)
        self.assertIn("Partial SBS-19", logs)
        os.remove(self.root / "server/prisma7.config.ts")

        # 2. Schema exists without canonical server/prisma7.config.ts
        self.write_valid_sbs19_contract()
        os.remove(self.root / "server/prisma7.config.ts")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("server/prisma7.config.ts must exist", logs)
        shutil.rmtree(self.root / "server/prisma")
        os.remove(self.root / "server/package.json")
        shutil.rmtree(self.root / "server/src/__tests__/database")

        # 3. Dependency prisma declared without schema
        self.write_file(
            "package-lock.json",
            json.dumps({"name": "test-root", "lockfileVersion": 3, "packages": {"": {"name": "test-root"}}}),
        )
        self.write_file(
            "server/package.json",
            json.dumps({"devDependencies": {"prisma": "7.10.1"}, "scripts": {"test": "tsx --test src/__tests__/*.test.ts"}}),
        )
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Partial SBS-19 dependency", logs)

        # 4. Partial DB script without schema
        self.write_file(
            "server/package.json",
            json.dumps({"scripts": {"db:validate": "prisma validate --schema=prisma/schema.prisma"}}),
        )
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Partial SBS-19 script", logs)

        # 5. server/prisma/migrations or seed.ts without schema
        self.write_file("server/package.json", json.dumps({"scripts": {"test": "tsx --test src/__tests__/*.test.ts"}}))
        self.write_file("server/prisma/seed.ts", "async function main() {}\n")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Partial SBS-19 artifact", logs)
        shutil.rmtree(self.root / "server/prisma")

        # 6. Database test dir without schema
        self.write_file("server/src/__tests__/database/integrity.test.ts", "test('x', () => {});\n")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Partial SBS-19 artifact", logs)
        shutil.rmtree(self.root / "server/src/__tests__/database")

        # 7. Forbidden alias on baseline without schema
        self.write_file("prisma.config.ts", "export default {};\n")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Alternate Prisma config file", logs)

    def test_accepts_valid_direct_commands_and_canonical_schema(self) -> None:
        valid_variants = [
            {"db:validate": "prisma validate --schema=prisma/schema.prisma"},
            {"db:validate": "prisma validate --schema prisma/schema.prisma"},
            {"db:migrate:deploy": "prisma migrate deploy --schema=prisma/schema.prisma"},
            {"db:migrate:deploy": "prisma migrate deploy --schema prisma/schema.prisma"},
            {"db:seed": "tsx prisma/seed.ts"},
            {"test:db": "node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"},
            {"test:db": "tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"},
            {
                "test:db": "NODE_ENV=test node --import tsx --test --test-reporter tap src/__tests__/database/integrity.test.ts"
            },
        ]
        for override in valid_variants:
            self.write_valid_sbs19_contract(overrides=override)
            code, gh_out, logs = self.run_check()
            self.assertEqual(code, 0, msg=f"Failed for valid script override {override}: {logs}")
            self.assertIn("run_prisma=true", gh_out)

    def test_rejects_omitted_or_alternate_schema_flags_and_config_redirection(self) -> None:
        bad_schema_cmds = [
            ("db:validate", "prisma validate"),
            ("db:validate", "prisma validate --schema=alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema=/tmp/schema.prisma"),
            ("db:validate", "prisma validate --schema=../other/schema.prisma"),
            ("db:validate", "prisma validate --schema=prisma/../alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema="),
            ("db:validate", 'prisma validate --schema ""'),
            ("db:validate", "prisma validate --schema"),
            ("db:validate", "prisma validate --schema=prisma/schema.prisma --schema=prisma/schema.prisma"),
            ("db:validate", "prisma validate --schema=prisma/schema.prisma --config=prisma7.config.ts"),
            ("db:validate", "prisma validate --schema=prisma/schema.prisma --config prisma.config.ts"),
            ("db:migrate:deploy", "prisma migrate deploy"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=alternate/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=/tmp/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=../other/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=prisma/../alternate/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema="),
            ("db:migrate:deploy", "prisma migrate deploy --schema"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=prisma/schema.prisma --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=prisma/schema.prisma --config=prisma.config.ts"),
            ("db:seed", "prisma db seed"),
            ("db:seed", "prisma db seed --schema=prisma/schema.prisma"),
            ("db:seed", "node --import tsx prisma/seed.ts"),
            ("db:seed", "tsx seed.ts"),
            ("db:seed", "tsx prisma/other-seed.ts"),
        ]
        for key, bad_cmd in bad_schema_cmds:
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, _ = self.run_check()
            self.assertEqual(
                code,
                1,
                msg=f"Regression: disallowed schema, config, or seed flag accepted for {key}: {bad_cmd!r}",
            )

    def test_rejects_package_json_prisma_redirection_and_invalid_json(self) -> None:
        for bad_prisma_cfg in (
            {"schema": "prisma/schema.prisma", "seed": "tsx prisma/seed.ts"},
            {"schema": "alternate/schema.prisma"},
            {"migrations": "alternate/migrations"},
            "prisma/schema.prisma",
        ):
            self.write_valid_sbs19_contract(prisma_cfg=bad_prisma_cfg)
            code, _, logs = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for server/package.json prisma={bad_prisma_cfg!r}")
            self.assertIn("legacy 'prisma'", logs)

        self.write_valid_sbs19_contract()
        self.write_file(
            "package.json",
            json.dumps({"name": "root", "workspaces": ["server"], "prisma": {"schema": "server/prisma/schema.prisma"}}),
        )
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Root package.json cannot define a 'prisma'", logs)

        self.write_valid_sbs19_contract()
        self.write_file("server/package.json", "{ invalid json")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_valid_sbs19_contract()
        self.write_file("package.json", "{ invalid json")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_rejects_npx_and_npm_exec_wrappers_across_all_four_scripts(self) -> None:
        wrapper_cmds = [
            ("db:validate", "npx prisma validate --schema=prisma/schema.prisma"),
            ("db:validate", "npx --no-install prisma validate --schema=prisma/schema.prisma"),
            ("db:validate", "npm exec -- prisma validate --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "npx prisma migrate deploy --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "npm exec -- prisma migrate deploy --schema=prisma/schema.prisma"),
            ("db:seed", "npx tsx prisma/seed.ts"),
            ("db:seed", "npm exec -- tsx prisma/seed.ts"),
            ("test:db", "npx tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("test:db", "npm exec -- node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("db:validate", "npx ./ci-bin/prisma validate --schema=prisma/schema.prisma"),
            ("db:validate", "npm exec -- ./ci-bin/prisma validate --schema=prisma/schema.prisma"),
        ]
        for key, bad_cmd in wrapper_cmds:
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, logs = self.run_check()
            self.assertEqual(
                code,
                1,
                msg=f"Regression: wrapper command accepted for {key}: {bad_cmd!r}",
            )
            self.assertTrue(
                "cannot invoke" in logs or "path-qualified" in logs,
                msg=f"Unexpected error message for wrapper {bad_cmd!r}: {logs}",
            )

    def test_rejects_path_qualified_executables_and_prefixes(self) -> None:
        bad_executables = [
            ("db:validate", "./ci-bin/prisma validate --schema=prisma/schema.prisma"),
            ("db:validate", "/tmp/prisma validate --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "./ci-bin/prisma migrate deploy --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "fake-bin/prisma migrate deploy --schema=prisma/schema.prisma"),
            ("db:seed", "./ci-bin/tsx prisma/seed.ts"),
            ("test:db", "./ci-bin/node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("db:validate", "./ci-bin/npx prisma validate --schema=prisma/schema.prisma"),
            ("db:validate", "./ci-bin/npm exec -- prisma validate --schema=prisma/schema.prisma"),
        ]
        for key, bad_cmd in bad_executables:
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, logs = self.run_check()
            self.assertEqual(
                code,
                1,
                msg=f"Regression: path-qualified executable was accepted for {key}: {bad_cmd!r}",
            )
            self.assertIn("path-qualified", logs)

    def test_rejects_path_and_env_manipulation_assignments(self) -> None:
        bad_env_cases = [
            ("db:validate", "PATH=./ci-bin prisma validate --schema=prisma/schema.prisma", "PATH"),
            ("db:migrate:deploy", "PATH=./ci-bin prisma migrate deploy --schema=prisma/schema.prisma", "PATH"),
            ("db:seed", "PATH=./ci-bin tsx prisma/seed.ts", "PATH"),
            (
                "test:db",
                "PATH=./ci-bin node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
                "PATH",
            ),
            (
                "test:db",
                "NODE_PATH=./ci-bin node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
                "NODE_PATH",
            ),
            (
                "test:db",
                "NODE_OPTIONS=--inspect node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
                "NODE_OPTIONS",
            ),
            ("db:validate", "HOME=./fake-home prisma validate --schema=prisma/schema.prisma", "HOME"),
            ("db:validate", "IFS=/ prisma validate --schema=prisma/schema.prisma", "IFS"),
            ("db:validate", "BASH_ENV=./evil.sh prisma validate --schema=prisma/schema.prisma", "BASH_ENV"),
            ("db:validate", "ENV=./evil.sh prisma validate --schema=prisma/schema.prisma", "ENV"),
            ("db:validate", "NODE_ENV=test prisma validate --schema=prisma/schema.prisma", "NODE_ENV"),
            ("db:migrate:deploy", "NODE_ENV=test prisma migrate deploy --schema=prisma/schema.prisma", "NODE_ENV"),
            ("db:seed", "NODE_ENV=test tsx prisma/seed.ts", "NODE_ENV"),
            (
                "test:db",
                "NODE_ENV=production node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
                "NODE_ENV",
            ),
            (
                "test:db",
                "NODE_ENV=test NODE_ENV=test node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
                "NODE_ENV",
            ),
        ]
        for key, bad_cmd, expected_var in bad_env_cases:
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, logs = self.run_check()
            self.assertEqual(
                code,
                1,
                msg=f"Regression: unsafe env assignment accepted for {key}: {bad_cmd!r}",
            )
            self.assertIn(expected_var, logs)
            self.assertNotIn("./ci-bin", logs)
            self.assertNotIn("./fake-home", logs)
            self.assertNotIn("--inspect", logs)

    def test_rejects_deleted_schema_from_base(self) -> None:
        self.write_valid_sbs19_contract()
        base_with_schema = self.commit_all("sbs19 base")
        os.remove(self.root / "server/prisma/schema.prisma")
        code, gh_out, logs = self.run_check(base_sha=base_with_schema)
        self.assertEqual(code, 1)
        self.assertIn("run_prisma=false", gh_out)
        self.assertIn("cannot be deleted", logs)

    def test_rejects_empty_and_comment_only_migrations(self) -> None:
        self.write_valid_sbs19_contract()
        self.write_file("server/prisma/migrations/20261126000001_empty/migration.sql", "   \n  ")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/prisma/migrations/20261126000001_empty/migration.sql",
            "-- SQL comment only\n/* block comment\n   with semicolons ;;; */\n;\n",
        )
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_rejects_missing_or_wrong_provider_migration_lock(self) -> None:
        self.write_valid_sbs19_contract()
        os.remove(self.root / "server/prisma/migrations/migration_lock.toml")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file("server/prisma/migrations/migration_lock.toml", 'provider = "sqlite"\n')
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_rejects_placeholder_and_generic_scripts(self) -> None:
        bad_cases = {
            "db:validate": "echo 'TODO'",
            "db:migrate:deploy": "exit 0",
            "db:seed": "true",
            "test:db": "npm test",
        }
        for key, bad_cmd in bad_cases.items():
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for {key}={bad_cmd!r}")

        for extra_bad_test_db in (
            "tsx --test --test-reporter=tap src/__tests__/*.test.ts",
            "node --import tsx --test src/__tests__/database/*.test.ts",
            "tsx --test --test-reporter=tap src/__tests__/health.test.ts",
            'sh -c "tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"',
        ):
            self.write_valid_sbs19_contract(overrides={"test:db": extra_bad_test_db})
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for test:db={extra_bad_test_db!r}")

    def test_rejects_shell_chaining_and_unsafe_syntax_across_all_four_scripts(self) -> None:
        suffixes = (
            "; date",
            " || date",
            " | cat",
            " && true",
            " &",
            " > /dev/null",
            " $(date)",
            " `date`",
            " --unexpected-flag",
        )
        for key, valid_cmd in VALID_SCRIPTS.items():
            for suffix in suffixes:
                mutated = f"{valid_cmd}{suffix}"
                self.write_valid_sbs19_contract(overrides={key: mutated})
                code, _, logs = self.run_check()
                self.assertEqual(
                    code,
                    1,
                    msg=f"Regression: validator accepted unsafe command for {key}: {mutated!r}",
                )
                self.assertTrue(logs.strip(), msg=f"Expected failure reason for {key}: {mutated!r}")

    def test_rejects_unapproved_arguments_on_database_scripts(self) -> None:
        bad_args = {
            "db:validate": "prisma migrate reset --schema=prisma/schema.prisma",
            "db:migrate:deploy": "prisma migrate dev --schema=prisma/schema.prisma",
            "db:seed": "tsx src/server.ts",
            "test:db": "node --import tsx --test --test-reporter=tap src/__tests__/database/integrity.test.ts src/__tests__/health.test.ts",
        }
        for key, cmd in bad_args.items():
            self.write_valid_sbs19_contract(overrides={key: cmd})
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for {key}={cmd!r}")

    def test_rejects_missing_empty_or_non_runnable_database_tests(self) -> None:
        self.write_valid_sbs19_contract()
        os.remove(self.root / "server/src/__tests__/database/integrity.test.ts")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file("server/src/__tests__/database/integrity.test.ts", "   \n")
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            "// test('commented out', () => {});\n/* it('blocked', () => {}); */\nexport {};\n",
        )
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            'import test from "node:test";\ntest.skip("all skipped", () => {});\n',
        )
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_migration_immutability_blocks_edit_delete_rename_and_allows_addition(self) -> None:
        self.write_valid_sbs19_contract()
        base_with_mig = self.commit_all("add initial migration")

        self.write_file(
            "server/prisma/migrations/20261127000000_add_index/migration.sql",
            "CREATE INDEX idx_users_id ON users (id);\n",
        )
        code, _, _ = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 0)

        self.write_file(
            "server/prisma/migrations/20261126000000_init/migration.sql",
            "CREATE TABLE users (id TEXT PRIMARY KEY, modified TEXT);\n",
        )
        code, _, logs = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 1)
        self.assertIn("immutable", logs)

        os.remove(self.root / "server/prisma/migrations/20261126000000_init/migration.sql")
        code, _, logs = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 1)
        self.assertIn("cannot be deleted, symlinked, or renamed", logs)


class VersionAndLockfileTests(TempRepoTestCase):
    def test_accepts_exact_prisma_7_10_1_hoisted_and_nested_lockfile(self) -> None:
        for nested in (False, True):
            self.write_valid_sbs19_contract(nested_lock=nested)
            code, gh_out, logs = self.run_check()
            self.assertEqual(code, 0, msg=f"nested={nested} failed: {logs}")
            self.assertIn("run_prisma=true", gh_out)
            self.assertIn("Prisma 7.10.1", logs)

    def test_rejects_prisma_8_rc_prisma_6_ranges_mismatches_and_lockfile_drift(self) -> None:
        bad_version_cases = [
            dict(prisma_cli_version="8.0.0-rc.35", prisma_client_version="8.0.0-rc.35", lock_cli_version="8.0.0-rc.35", lock_client_version="8.0.0-rc.35"),
            dict(prisma_cli_version="6.19.0", prisma_client_version="6.19.0", lock_cli_version="6.19.0", lock_client_version="6.19.0"),
            dict(prisma_cli_version="^7.10.1"),
            dict(prisma_client_version="~7.10.1"),
            dict(prisma_cli_version="latest"),
            dict(prisma_cli_version="7.10.0"),
            dict(prisma_client_version="7.10.0"),
            dict(lock_cli_version="7.10.0"),
            dict(lock_client_version="8.0.0-rc.10"),
            dict(nested_lock=True, lock_cli_version="7.10.0"),
            dict(nested_lock=True, lock_client_version="6.19.0"),
        ]
        for case in bad_version_cases:
            self.write_valid_sbs19_contract(**case)
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Version contract accepted disallowed version spec: {case!r}")

    def test_rejects_missing_or_misplaced_prisma_dependencies_or_lockfile(self) -> None:
        self.write_valid_sbs19_contract()
        # Missing prisma from package-lock.json
        self.write_file("package-lock.json", json.dumps({"name": "root", "lockfileVersion": 3, "packages": {}}))
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        # server/package-lock.json forbidden
        self.write_valid_sbs19_contract()
        self.write_file("server/package-lock.json", "{}")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("server/package-lock.json", logs)
        os.remove(self.root / "server/package-lock.json")

        # prisma placed in server dependencies instead of devDependencies
        self.write_valid_sbs19_contract()
        pkg = json.loads((self.root / "server/package.json").read_text(encoding="utf-8"))
        pkg["dependencies"]["prisma"] = "7.10.1"
        self.write_file("server/package.json", json.dumps(pkg))
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

        # root package.json overrides prisma
        self.write_valid_sbs19_contract()
        self.write_file(
            "package.json",
            json.dumps({"name": "root", "workspaces": ["server"], "overrides": {"prisma": "8.0.0-rc.35"}}),
        )
        code, _, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_verify_runtime_versions_subcommand(self) -> None:
        self.write_file("node_modules/prisma/package.json", json.dumps({"name": "prisma", "version": "7.10.1"}))
        self.write_file("node_modules/@prisma/client/package.json", json.dumps({"name": "@prisma/client", "version": "7.10.1"}))
        code, logs = self.run_runtime_version_check()
        self.assertEqual(code, 0, msg=logs)

        # Nested server/node_modules mismatch overrides root
        self.write_file("server/node_modules/prisma/package.json", json.dumps({"name": "prisma", "version": "8.0.0-rc.35"}))
        code, logs = self.run_runtime_version_check()
        self.assertEqual(code, 1)
        self.assertIn("8.0.0-rc.35", logs)


class CanonicalConfigTests(TempRepoTestCase):
    def test_accepts_canonical_config_and_safe_formatting_variants(self) -> None:
        self.write_valid_sbs19_contract(config_content=CANONICAL_CONFIG_CONTENT)
        code, _, logs = self.run_check()
        self.assertEqual(code, 0, msg=logs)

        single_quote_variant = """import dotenv from 'dotenv'
import path from 'node:path'
import { fileURLToPath, } from 'node:url'
import { defineConfig, } from 'prisma/config'

const configDirectory = path.dirname(fileURLToPath(import.meta.url))

dotenv.config({
  override: false,
  path: path.resolve(configDirectory, '../.env'),
})

export default defineConfig({
  datasource: {
    url: process.env['DATABASE_URL'],
  },
  migrations: {
    path: 'prisma/migrations',
  },
  schema: 'prisma/schema.prisma',
})
"""
        self.write_valid_sbs19_contract(config_content=single_quote_variant)
        code, _, logs = self.run_check()
        self.assertEqual(code, 0, msg=logs)

    def test_fixture_file_does_not_trigger_partial_sbs19_or_forbidden_config(self) -> None:
        self.write_file(
            "server/package.json",
            json.dumps({"scripts": {"test": "tsx --test src/__tests__/*.test.ts"}}),
        )
        self.write_file(".github/fixtures/prisma7.config.ts", CANONICAL_CONFIG_CONTENT)
        self.assertEqual(v.detect_partial_sbs19_artifacts(str(self.root)), [])
        code, gh_out, logs = self.run_check()
        self.assertEqual(code, 0, msg=logs)
        self.assertIn("run_prisma=false", gh_out)

    def test_rejects_wrong_root_env_resolution_override_and_dynamic_config(self) -> None:
        old_dotenv_import_cfg = """import "dotenv/config";
import { defineConfig } from "prisma/config";

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations",
  },
  datasource: {
    url: process.env["DATABASE_URL"],
  },
});
"""
        bad_configs = [
            "",
            old_dotenv_import_cfg,
            CANONICAL_CONFIG_CONTENT.replace(
                'path: path.resolve(configDirectory, "../.env"),\n  override: false,',
                "",
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                '"../.env"',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                '".env"',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(process.cwd(), "../.env")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(configDirectory, "./.env")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(configDirectory, "../../.env")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(configDirectory, "server/.env")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(configDirectory, "../.env.local")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'path.resolve(configDirectory, "../.env.production")',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'process.env["DOTENV_PATH"]',
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path.resolve(configDirectory, "../.env")',
                'process.env["DOTENV_CONFIG_PATH"]',
            ),
            CANONICAL_CONFIG_CONTENT.replace("override: false", "override: true"),
            CANONICAL_CONFIG_CONTENT.replace("  override: false,\n", ""),
            CANONICAL_CONFIG_CONTENT.replace(
                "override: false,",
                "override: false,\n  override: false,",
            ),
            CANONICAL_CONFIG_CONTENT.replace(
                'path: path.resolve(configDirectory, "../.env"),',
                'path: path.resolve(configDirectory, "../.env"),\n  path: path.resolve(configDirectory, "../.env"),',
            ),
            CANONICAL_CONFIG_CONTENT.replace("  override: false,", "...extraDotenvOpts,\n  override: false,"),
            CANONICAL_CONFIG_CONTENT.replace("override: false,", '["override"]: false,'),
            CANONICAL_CONFIG_CONTENT.replace('"prisma/schema.prisma"', '"prisma/alt.prisma"'),
            CANONICAL_CONFIG_CONTENT.replace('"prisma/migrations"', '"prisma/alt_migrations"'),
            CANONICAL_CONFIG_CONTENT.replace('process.env["DATABASE_URL"]', '"postgresql://user:pass@localhost/db"'),
            CANONICAL_CONFIG_CONTENT.replace('process.env["DATABASE_URL"]', 'process.env["CUSTOM_DB_URL"]'),
            CANONICAL_CONFIG_CONTENT.replace('process.env["DATABASE_URL"]', 'env("DATABASE_URL")'),
            CANONICAL_CONFIG_CONTENT.replace('process.env["DATABASE_URL"]', 'process.env["DATABASE_URL"] || ""'),
            'import { readFileSync } from "node:fs";\n' + CANONICAL_CONFIG_CONTENT,
            CANONICAL_CONFIG_CONTENT.replace('schema: "prisma/schema.prisma",', '...baseConfig,\n  schema: "prisma/schema.prisma",'),
            CANONICAL_CONFIG_CONTENT.replace('schema: "prisma/schema.prisma",', '["schema"]: "prisma/schema.prisma",'),
            CANONICAL_CONFIG_CONTENT.replace('schema: "prisma/schema.prisma",', 'schema: true ? "prisma/schema.prisma" : "other.prisma",'),
            CANONICAL_CONFIG_CONTENT.replace('schema: "prisma/schema.prisma",', 'schema: getSchema(),'),
            CANONICAL_CONFIG_CONTENT.replace('schema: "prisma/schema.prisma",', 'schema: `prisma/schema.prisma`,'),
            CANONICAL_CONFIG_CONTENT + '\nconsole.log("side effect");\n',
            "// hidden comment\n" + CANONICAL_CONFIG_CONTENT,
            CANONICAL_CONFIG_CONTENT.replace("prisma/config", r"\x70risma/config"),
        ]
        for bad_cfg in bad_configs:
            self.write_valid_sbs19_contract(config_content=bad_cfg)
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Accepted invalid prisma7.config.ts:\n{bad_cfg}")

    def test_rejects_symlinks_for_canonical_config_and_schema(self) -> None:
        self.write_valid_sbs19_contract()
        target = self.root / "external.ts"
        target.write_text(CANONICAL_CONFIG_CONTENT, encoding="utf-8")
        os.remove(self.root / "server/prisma7.config.ts")
        os.symlink(target, self.root / "server/prisma7.config.ts")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Symlink", logs)

        self.write_valid_sbs19_contract()
        schema_target = self.root / "alt-schema.prisma"
        schema_target.write_text('datasource db {\n  provider = "postgresql"\n}\n', encoding="utf-8")
        os.remove(self.root / "server/prisma/schema.prisma")
        os.symlink(schema_target, self.root / "server/prisma/schema.prisma")
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("Symlink", logs)


class ConfigDiscoveryAliasTests(TempRepoTestCase):
    def test_rejects_every_alternate_config_filename_extension_directory_and_symlink(self) -> None:
        extensions = (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts")
        basenames = (
            "prisma.config",
            "prisma7.config",
            ".config/prisma",
            ".config/prisma7",
            ".config/prisma.config",
            ".config/prisma7.config",
        )
        candidates: list[str] = []
        for prefix in ("", "server/"):
            for base in basenames:
                for ext in extensions:
                    direct = f"{prefix}{base}{ext}"
                    if direct != "server/prisma7.config.ts":
                        candidates.append(direct)
                    candidates.append(f"{prefix}{base}/index{ext}")

        self.write_valid_sbs19_contract()
        for rel in candidates:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export default {};\n", encoding="utf-8")
            code, _, logs = self.run_check()
            self.assertEqual(code, 1, msg=f"Regression: Prisma config alias '{rel}' was NOT rejected!")
            self.assertIn(rel, logs)
            target.unlink()
            # Clean directory if we created index.* subdir
            if rel.endswith(f"/index{Path(rel).suffix}") and target.parent.exists():
                target.parent.rmdir()

        # Also test dangling symlink alias and stray alternate schema files
        dangling = self.root / "prisma.config.ts"
        os.symlink("/nonexistent/prisma.config.ts", dangling)
        code, _, logs = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("prisma.config.ts", logs)
        dangling.unlink()

        for stray_schema in ("schema.prisma", "prisma/schema.prisma", "server/schema.prisma"):
            self.write_file(stray_schema, 'datasource db { provider = "postgresql" }\n')
            code, _, logs = self.run_check()
            self.assertEqual(code, 1, msg=f"Stray schema {stray_schema} not rejected")
            self.assertIn(stray_schema, logs)
            os.remove(self.root / stray_schema)


class WorkspaceResolutionTests(unittest.TestCase):
    def test_npm_workspace_runs_inside_server_directory_where_canonical_config_resolves(self) -> None:
        npm_bin = shutil.which("npm")
        if not npm_bin:
            self.skipTest("npm binary is unavailable in environment")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"name": "ws-probe", "private": True, "workspaces": ["server"]}, indent=2),
                encoding="utf-8",
            )
            (root / "server/prisma/migrations").mkdir(parents=True, exist_ok=True)
            (root / "server/prisma7.config.ts").write_text(CANONICAL_CONFIG_CONTENT, encoding="utf-8")
            (root / "server/prisma/schema.prisma").write_text(
                'datasource db {\n  provider = "postgresql"\n}\n', encoding="utf-8"
            )
            probe_js = (
                "const fs=require('fs'),path=require('path');"
                "console.log(JSON.stringify({"
                "cwd:fs.realpathSync(process.cwd()),"
                "hasCfg:fs.existsSync('prisma7.config.ts'),"
                "hasSchema:fs.existsSync(path.join('prisma','schema.prisma'))"
                "}))"
            )
            (root / "server/package.json").write_text(
                json.dumps(
                    {
                        "name": "sbs-server-probe",
                        "private": True,
                        "scripts": {"probe:ws": f'node -e "{probe_js}"'},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            res = subprocess.run(
                [npm_bin, "run", "--silent", "probe:ws", "--workspace=server"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            payload = json.loads(res.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["cwd"], str((root / "server").resolve()))
            self.assertTrue(payload["hasCfg"])
            self.assertTrue(payload["hasSchema"])


class BaseResolutionAndMigrationFailClosedTests(TempRepoTestCase):
    def test_pull_request_base_ref_resolution_valid_empty_and_missing(self) -> None:
        ref, err = v.resolve_base_ref(str(self.root), "pull_request", self.base_sha)
        self.assertEqual(ref, self.base_sha)
        self.assertIsNone(err)

        ref, err = v.resolve_base_ref(str(self.root), "pull_request", "")
        self.assertIsNone(ref)
        self.assertIsNotNone(err)

        ref, err = v.resolve_base_ref(str(self.root), "pull_request", "deadbeefdeadbeef")
        self.assertIsNone(ref)
        self.assertIsNotNone(err)

    def test_push_event_uses_before_sha_and_fails_without_valid_base(self) -> None:
        ref, err = v.resolve_base_ref(str(self.root), "push", self.base_sha)
        self.assertEqual(ref, self.base_sha)
        self.assertIsNone(err)

        for bad_before in ("", "0" * 40, "not-a-sha"):
            ref, err = v.resolve_base_ref(str(self.root), "push", bad_before)
            self.assertIsNone(ref)
            self.assertIsNotNone(err)
            code, _, _ = self.run_check(event_name="push", base_sha=bad_before)
            self.assertEqual(code, 1)

    def test_workflow_dispatch_resolves_parent_and_fails_closed_when_unavailable(self) -> None:
        ref, err = v.resolve_base_ref(str(self.root), "workflow_dispatch", "")
        self.assertIsNone(ref)
        self.assertIsNotNone(err)
        code, _, _ = self.run_check(event_name="workflow_dispatch", base_sha="")
        self.assertEqual(code, 1)

        self.write_file("README.md", "# Updated repo\n")
        self.commit_all("second commit")
        ref, err = v.resolve_base_ref(str(self.root), "workflow_dispatch", "")
        self.assertEqual(ref, self.base_sha)
        self.assertIsNone(err)
        code, _, _ = self.run_check(event_name="workflow_dispatch", base_sha="")
        self.assertEqual(code, 0)

        real_run_git = v.run_git

        def fake_rev_parse(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "rev-parse":
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=128,
                    stdout="",
                    stderr="fatal: rev-parse failed",
                )
            return real_run_git(repo_root, args)

        with mock.patch.object(v, "run_git", side_effect=fake_rev_parse):
            ref, err = v.resolve_base_ref(str(self.root), "workflow_dispatch", "")
            self.assertIsNone(ref)
            self.assertIsNotNone(err)

    def test_get_base_migrations_reads_valid_entries_empty_and_rejects_failures(self) -> None:
        fake_stdout = (
            "100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tserver/prisma/migrations/migration_lock.toml\n"
            "100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\tserver/prisma/migrations/20261126000000_init/migration.sql\n"
        )
        completed = subprocess.CompletedProcess(
            args=["git", "ls-tree"],
            returncode=0,
            stdout=fake_stdout,
            stderr="",
        )
        with mock.patch.object(v, "run_git", return_value=completed):
            result = v.get_base_migrations(str(self.root), "deadbeef")
        self.assertEqual(
            result,
            {
                "server/prisma/migrations/20261126000000_init/migration.sql": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
        )

        empty_ok = subprocess.CompletedProcess(args=["git", "ls-tree"], returncode=0, stdout="", stderr="")
        with mock.patch.object(v, "run_git", return_value=empty_ok):
            self.assertEqual(v.get_base_migrations(str(self.root), "deadbeef"), {})

        with self.assertRaises(v.GitInspectionError):
            v.get_base_migrations(str(self.root), "")

        failed = subprocess.CompletedProcess(
            args=["git", "ls-tree"],
            returncode=128,
            stdout="",
            stderr="fatal: bad tree object",
        )
        with mock.patch.object(v, "run_git", return_value=failed):
            with self.assertRaises(v.GitInspectionError):
                v.get_base_migrations(str(self.root), "deadbeef")

    def test_check_schema_and_contract_fails_when_ls_tree_fails_even_without_schema(self) -> None:
        base_sha = self.base_sha
        real_run_git = v.run_git

        def fake_run_git(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "ls-tree":
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=128,
                    stdout="",
                    stderr="fatal: simulated ls-tree error",
                )
            return real_run_git(repo_root, args)

        with mock.patch.object(v, "run_git", side_effect=fake_run_git):
            code, _, logs = self.run_check(base_sha=base_sha)
        self.assertEqual(code, 1)
        self.assertIn("git ls-tree failed", logs)


class TapVerificationTests(unittest.TestCase):
    def _verify(self, tap_content: str) -> int:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(tap_content)
            path = tf.name
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                return v.main(["verify-tap", "--tap-file", path])
        finally:
            os.remove(path)

    def test_accepts_passing_tap_summary(self) -> None:
        tap = (
            "TAP version 13\n"
            "ok 1 - creates thesis safely\n"
            "ok 2 - enforces partial unique index\n"
            "1..2\n"
            "# tests 2\n"
            "# pass 2\n"
            "# fail 0\n"
            "# cancelled 0\n"
            "# skipped 0\n"
            "# todo 0\n"
        )
        self.assertEqual(self._verify(tap), 0)

    def test_rejects_zero_tests_failures_all_skipped_and_missing_summary(self) -> None:
        zero_tests = "TAP version 13\n1..0\n# tests 0\n# pass 0\n# fail 0\n"
        self.assertEqual(self._verify(zero_tests), 1)

        failing = (
            "TAP version 13\n"
            "ok 1 - passes\n"
            "not ok 2 - constraint failed\n"
            "1..2\n# tests 2\n# pass 1\n# fail 1\n"
        )
        self.assertEqual(self._verify(failing), 1)

        all_skipped = (
            "TAP version 13\n"
            "ok 1 - skipped # SKIP reason\n"
            "1..1\n# tests 1\n# pass 0\n# fail 0\n# skipped 1\n"
        )
        self.assertEqual(self._verify(all_skipped), 1)

        missing_summary = "TAP version 13\nok 1 - passes\n"
        self.assertEqual(self._verify(missing_summary), 1)


class StepSummaryTests(unittest.TestCase):
    def test_renders_baseline_na_summary_precisely(self) -> None:
        md = v.render_step_summary(
            validator_tests_outcome="success",
            pg_health_outcome="success",
            pg_connect_outcome="success",
            contract_outcome="success",
            run_prisma="false",
            prisma_outcome="skipped",
        )
        self.assertIn("| PostgreSQL infrastructure | PASS |", md)
        self.assertIn("| CI validator self-tests | PASS |", md)
        self.assertIn("| SBS-19 schema/script/migration contract | N/A |", md)
        self.assertIn("| Prisma application integration | N/A |", md)
        self.assertIn("| Overall Database Integration | SUCCESS |", md)

    def test_renders_full_sbs19_pass(self) -> None:
        md = v.render_step_summary(
            validator_tests_outcome="success",
            pg_health_outcome="success",
            pg_connect_outcome="success",
            contract_outcome="success",
            run_prisma="true",
            prisma_outcome="success",
        )
        self.assertIn("| PostgreSQL infrastructure | PASS |", md)
        self.assertIn("| CI validator self-tests | PASS |", md)
        self.assertIn("| SBS-19 schema/script/migration contract | PASS |", md)
        self.assertIn("| Prisma application integration | PASS |", md)
        self.assertIn("| Overall Database Integration | SUCCESS |", md)

    def test_renders_failure_when_any_check_fails_or_is_incomplete(self) -> None:
        cases = [
            dict(
                validator_tests_outcome="success",
                pg_health_outcome="failure",
                pg_connect_outcome="skipped",
                contract_outcome="skipped",
                run_prisma="",
                prisma_outcome="skipped",
                expected=("| PostgreSQL infrastructure | FAIL |", "| Overall Database Integration | FAILURE |"),
            ),
            dict(
                validator_tests_outcome="failure",
                pg_health_outcome="skipped",
                pg_connect_outcome="skipped",
                contract_outcome="skipped",
                run_prisma="",
                prisma_outcome="skipped",
                expected=("| CI validator self-tests | FAIL |", "| Overall Database Integration | FAILURE |"),
            ),
            dict(
                validator_tests_outcome="success",
                pg_health_outcome="success",
                pg_connect_outcome="success",
                contract_outcome="failure",
                run_prisma="false",
                prisma_outcome="skipped",
                expected=("| SBS-19 schema/script/migration contract | FAIL |", "| Prisma application integration | NOT COMPLETED |", "| Overall Database Integration | FAILURE |"),
            ),
            dict(
                validator_tests_outcome="success",
                pg_health_outcome="success",
                pg_connect_outcome="success",
                contract_outcome="success",
                run_prisma="true",
                prisma_outcome="failure",
                expected=("| Prisma application integration | FAIL |", "| Overall Database Integration | FAILURE |"),
            ),
            dict(
                validator_tests_outcome="success",
                pg_health_outcome="success",
                pg_connect_outcome="success",
                contract_outcome="skipped",
                run_prisma="",
                prisma_outcome="skipped",
                expected=("| SBS-19 schema/script/migration contract | NOT COMPLETED |", "| Overall Database Integration | FAILURE |"),
            ),
            dict(
                validator_tests_outcome="success",
                pg_health_outcome="success",
                pg_connect_outcome="success",
                contract_outcome="success",
                run_prisma="true",
                prisma_outcome="skipped",
                expected=("| Prisma application integration | NOT COMPLETED |", "| Overall Database Integration | FAILURE |"),
            ),
        ]
        for case in cases:
            expected = case.pop("expected")
            md = v.render_step_summary(**case)
            for snippet in expected:
                self.assertIn(snippet, md, msg=f"Missing {snippet!r} in:\n{md}")


if __name__ == "__main__":
    unittest.main()
