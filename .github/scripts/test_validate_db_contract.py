#!/usr/bin/env python3
"""Unit tests for .github/scripts/validate_db_contract.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_db_contract as v  # noqa: E402


VALID_SCRIPTS = {
    "db:validate": "prisma validate",
    "db:migrate:deploy": "prisma migrate deploy",
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

    def write_valid_sbs19_contract(self, test_script: str | None = None) -> None:
        self.write_file("server/prisma/schema.prisma", "datasource db {\n  provider = \"postgresql\"\n}\n")
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
        if test_script is not None:
            scripts["test:db"] = test_script
        self.write_file("server/package.json", json.dumps({"scripts": scripts}, indent=2))

    def run_check(self, event_name: str = "pull_request", base_sha: str | None = None) -> tuple[int, str]:
        gh_out = self.root / ".gh_out"
        gh_out.write_text("", encoding="utf-8")
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
        return code, gh_out.read_text(encoding="utf-8")


class DatabaseContractValidatorTests(TempRepoTestCase):
    def test_pre_sbs19_baseline_returns_na_and_passes(self) -> None:
        self.write_file("server/package.json", json.dumps({"scripts": {"test": "tsx --test src/__tests__/*.test.ts"}}))
        code, out = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("run_prisma=false", out)

    def test_valid_sbs19_contract_passes_with_node_import_tsx_and_tsx_test(self) -> None:
        for script_cmd in (
            "node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
            "tsx --test --test-reporter=tap src/__tests__/database/*.test.ts",
            "NODE_ENV=test node --import tsx --test --test-reporter tap src/__tests__/database/integrity.test.ts",
        ):
            self.write_valid_sbs19_contract(test_script=script_cmd)
            code, out = self.run_check()
            self.assertEqual(code, 0, msg=f"Failed for valid script: {script_cmd}")
            self.assertIn("run_prisma=true", out)

    def test_rejects_deleted_schema_from_base(self) -> None:
        self.write_valid_sbs19_contract()
        base_with_schema = self.commit_all("sbs19 base")
        os.remove(self.root / "server/prisma/schema.prisma")
        code, out = self.run_check(base_sha=base_with_schema)
        self.assertEqual(code, 1)
        self.assertIn("run_prisma=false", out)

    def test_rejects_empty_and_comment_only_migrations(self) -> None:
        self.write_valid_sbs19_contract()
        self.write_file("server/prisma/migrations/20261126000001_empty/migration.sql", "   \n  ")
        code, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/prisma/migrations/20261126000001_empty/migration.sql",
            "-- SQL comment only\n/* block comment\n   with semicolons ;;; */\n;\n",
        )
        code, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_rejects_missing_or_wrong_provider_migration_lock(self) -> None:
        self.write_valid_sbs19_contract()
        os.remove(self.root / "server/prisma/migrations/migration_lock.toml")
        code, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file("server/prisma/migrations/migration_lock.toml", 'provider = "sqlite"\n')
        code, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_rejects_placeholder_and_generic_scripts(self) -> None:
        bad_cases = {
            "db:validate": "echo 'TODO'",
            "db:migrate:deploy": "exit 0",
            "db:seed": "true",
            "test:db": "npm test",
        }
        for key, bad_cmd in bad_cases.items():
            self.write_valid_sbs19_contract()
            scripts = dict(VALID_SCRIPTS)
            scripts[key] = bad_cmd
            self.write_file("server/package.json", json.dumps({"scripts": scripts}))
            code, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for {key}={bad_cmd!r}")

        for extra_bad_test_db in (
            "tsx --test --test-reporter=tap src/__tests__/*.test.ts",
            "node --import tsx --test src/__tests__/database/*.test.ts",
            "node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts || true",
        ):
            self.write_valid_sbs19_contract(test_script=extra_bad_test_db)
            code, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for test:db={extra_bad_test_db!r}")

    def test_rejects_missing_empty_or_non_runnable_database_tests(self) -> None:
        self.write_valid_sbs19_contract()
        os.remove(self.root / "server/src/__tests__/database/integrity.test.ts")
        code, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            "   \n",
        )
        code, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            "// test('commented out', () => {});\n/* it('blocked', () => {}); */\nexport {};\n",
        )
        code, _ = self.run_check()
        self.assertEqual(code, 1)

        self.write_file(
            "server/src/__tests__/database/integrity.test.ts",
            'import test from "node:test";\ntest.skip("all skipped", () => {});\n',
        )
        code, _ = self.run_check()
        self.assertEqual(code, 1)

    def test_migration_immutability_blocks_edit_delete_rename_and_allows_addition(self) -> None:
        self.write_valid_sbs19_contract()
        base_with_mig = self.commit_all("add initial migration")

        # Adding a new migration succeeds
        self.write_file(
            "server/prisma/migrations/20261127000000_add_index/migration.sql",
            "CREATE INDEX idx_users_id ON users (id);\n",
        )
        code, _ = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 0)

        # Modifying old migration fails
        self.write_file(
            "server/prisma/migrations/20261126000000_init/migration.sql",
            "CREATE TABLE users (id TEXT PRIMARY KEY, modified TEXT);\n",
        )
        code, _ = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 1)

        # Deleting / renaming old migration fails
        os.remove(self.root / "server/prisma/migrations/20261126000000_init/migration.sql")
        code, _ = self.run_check(base_sha=base_with_mig)
        self.assertEqual(code, 1)


class TapVerificationTests(unittest.TestCase):
    def _verify(self, tap_content: str) -> int:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(tap_content)
            path = tf.name
        try:
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


if __name__ == "__main__":
    unittest.main()
