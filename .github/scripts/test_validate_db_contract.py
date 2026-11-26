#!/usr/bin/env python3
"""Unit tests for .github/scripts/validate_db_contract.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
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

    def write_valid_sbs19_contract(
        self,
        overrides: dict[str, str] | None = None,
        prisma_cfg: object | None = None,
    ) -> None:
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
        pkg_obj: dict[str, object] = {"scripts": scripts}
        if prisma_cfg is not None:
            pkg_obj["prisma"] = prisma_cfg
        self.write_file("server/package.json", json.dumps(pkg_obj, indent=2))

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

    def test_accepts_valid_direct_commands_and_canonical_schema(self) -> None:
        valid_variants = [
            {"db:validate": "prisma validate"},
            {"db:validate": "prisma validate --schema=prisma/schema.prisma"},
            {"db:validate": "prisma validate --schema prisma/schema.prisma"},
            {"db:migrate:deploy": "prisma migrate deploy"},
            {"db:migrate:deploy": "prisma migrate deploy --schema=prisma/schema.prisma"},
            {"db:migrate:deploy": "prisma migrate deploy --schema prisma/schema.prisma"},
            {"db:seed": "prisma db seed"},
            {"db:seed": "prisma db seed --schema=prisma/schema.prisma"},
            {"db:seed": "tsx prisma/seed.ts"},
            {"db:seed": "node --import tsx prisma/seed.ts"},
            {"test:db": "node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"},
            {"test:db": "tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"},
            {
                "test:db": "NODE_ENV=test node --import tsx --test --test-reporter tap src/__tests__/database/integrity.test.ts"
            },
        ]
        for override in valid_variants:
            self.write_valid_sbs19_contract(overrides=override)
            code, gh_out, _ = self.run_check()
            self.assertEqual(code, 0, msg=f"Failed for valid script override: {override}")
            self.assertIn("run_prisma=true", gh_out)

    def test_rejects_alternate_schema_paths_traversal_and_config_redirection(self) -> None:
        bad_schema_cmds = [
            ("db:validate", "prisma validate --schema=alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema=/tmp/schema.prisma"),
            ("db:validate", "prisma validate --schema=../other/schema.prisma"),
            ("db:validate", "prisma validate --schema=prisma/../alternate/schema.prisma"),
            ("db:validate", "prisma validate --schema="),
            ("db:validate", 'prisma validate --schema ""'),
            ("db:validate", "prisma validate --schema"),
            ("db:validate", "prisma validate --schema=prisma/schema.prisma --schema=prisma/schema.prisma"),
            ("db:validate", "prisma validate --config=prisma.config.ts"),
            ("db:validate", "prisma validate --config prisma.config.ts"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=alternate/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=/tmp/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=../other/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=prisma/../alternate/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --schema="),
            ("db:migrate:deploy", "prisma migrate deploy --schema"),
            ("db:migrate:deploy", "prisma migrate deploy --schema=prisma/schema.prisma --schema=prisma/schema.prisma"),
            ("db:migrate:deploy", "prisma migrate deploy --config=prisma.config.ts"),
        ]
        for key, bad_cmd in bad_schema_cmds:
            self.write_valid_sbs19_contract(overrides={key: bad_cmd})
            code, _, _ = self.run_check()
            self.assertEqual(
                code,
                1,
                msg=f"Regression: non-canonical schema or config flag accepted for {key}: {bad_cmd!r}",
            )

        for cfg_rel in ("server/prisma.config.ts", "server/prisma.config.mjs", "prisma.config.ts"):
            self.write_valid_sbs19_contract()
            self.write_file(cfg_rel, "export default { schema: 'alternate/schema.prisma' };\n")
            code, _, logs = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection when {cfg_rel} exists")
            self.assertIn("not permitted", logs)
            os.remove(self.root / cfg_rel)

        self.write_valid_sbs19_contract(prisma_cfg={"schema": "prisma/schema.prisma", "seed": "tsx prisma/seed.ts"})
        code, _, _ = self.run_check()
        self.assertEqual(code, 0)

        for bad_prisma_cfg in (
            {"schema": "alternate/schema.prisma"},
            {"migrations": "alternate/migrations"},
            {"schema": "prisma/schema.prisma", "seed": "npx tsx prisma/seed.ts"},
        ):
            self.write_valid_sbs19_contract(prisma_cfg=bad_prisma_cfg)
            code, _, _ = self.run_check()
            self.assertEqual(code, 1, msg=f"Expected rejection for server/package.json prisma={bad_prisma_cfg!r}")

    def test_rejects_npx_and_npm_exec_wrappers_across_all_four_scripts(self) -> None:
        wrapper_cmds = [
            ("db:validate", "npx prisma validate"),
            ("db:validate", "npx --no-install prisma validate"),
            ("db:validate", "npm exec -- prisma validate"),
            ("db:migrate:deploy", "npx prisma migrate deploy"),
            ("db:migrate:deploy", "npm exec -- prisma migrate deploy"),
            ("db:seed", "npx tsx prisma/seed.ts"),
            ("db:seed", "npm exec -- tsx prisma/seed.ts"),
            ("test:db", "npx tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("test:db", "npm exec -- node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("db:validate", "npx ./ci-bin/prisma validate"),
            ("db:validate", "npm exec -- ./ci-bin/prisma validate"),
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
            ("db:validate", "./ci-bin/prisma validate"),
            ("db:validate", "/tmp/prisma validate"),
            ("db:migrate:deploy", "./ci-bin/prisma migrate deploy"),
            ("db:migrate:deploy", "fake-bin/prisma migrate deploy"),
            ("db:seed", "./ci-bin/tsx prisma/seed.ts"),
            ("test:db", "./ci-bin/node --import tsx --test --test-reporter=tap src/__tests__/database/*.test.ts"),
            ("db:validate", "./ci-bin/npx prisma validate"),
            ("db:validate", "./ci-bin/npm exec -- prisma validate"),
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
            ("db:validate", "PATH=./ci-bin prisma validate", "PATH"),
            ("db:migrate:deploy", "PATH=./ci-bin prisma migrate deploy", "PATH"),
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
            ("db:validate", "HOME=./fake-home prisma validate", "HOME"),
            ("db:validate", "IFS=/ prisma validate", "IFS"),
            ("db:validate", "BASH_ENV=./evil.sh prisma validate", "BASH_ENV"),
            ("db:validate", "ENV=./evil.sh prisma validate", "ENV"),
            ("db:validate", "NODE_ENV=test prisma validate", "NODE_ENV"),
            ("db:migrate:deploy", "NODE_ENV=test prisma migrate deploy", "NODE_ENV"),
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
            "db:validate": "prisma migrate reset",
            "db:migrate:deploy": "prisma migrate dev",
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
        self.assertIn("cannot be deleted or renamed", logs)


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
        # On root commit (no HEAD^), workflow_dispatch must fail closed
        ref, err = v.resolve_base_ref(str(self.root), "workflow_dispatch", "")
        self.assertIsNone(ref)
        self.assertIsNotNone(err)
        code, _, _ = self.run_check(event_name="workflow_dispatch", base_sha="")
        self.assertEqual(code, 1)

        # After a second commit, workflow_dispatch resolves parent HEAD^
        self.write_file("README.md", "# Updated repo\n")
        self.commit_all("second commit")
        ref, err = v.resolve_base_ref(str(self.root), "workflow_dispatch", "")
        self.assertEqual(ref, self.base_sha)
        self.assertIsNone(err)
        code, _, _ = self.run_check(event_name="workflow_dispatch", base_sha="")
        self.assertEqual(code, 0)

        # Mocked git rev-parse failure fails closed
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
