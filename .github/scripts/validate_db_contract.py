#!/usr/bin/env python3
"""CI validator for SBS-19 Prisma schema, migration, script contract, and TAP results."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from typing import Iterable


PLACEHOLDER_COMMANDS = {"true", ":", "echo", "printf"}
WRAPPER_EXECUTABLES = {"npx", "pnpx", "bunx"}
JS_RUNNERS = {"node", "tsx", "ts-node", "bun"}
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")
JS_LINE_COMMENT_RE = re.compile(r"//[^\r\n]*")
RUNNABLE_TEST_RE = re.compile(r"(?<![.\w])(?:test|it)\s*\(")
LOCK_PROVIDER_RE = re.compile(r"""^\s*provider\s*=\s*(["'])([^"']+)\1\s*$""")
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


def run_git(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def git_object_exists(repo_root: str, rev_spec: str) -> bool:
    res = run_git(repo_root, ["cat-file", "-e", rev_spec])
    return res.returncode == 0


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def resolve_base_ref(
    repo_root: str, event_name: str, base_sha: str | None
) -> tuple[str | None, str | None]:
    clean_base = (base_sha or "").strip()
    if event_name == "pull_request":
        if not clean_base:
            return None, "pull_request event is missing base commit SHA."
        if not git_object_exists(repo_root, f"{clean_base}^{{commit}}"):
            return (
                None,
                f"Base commit {clean_base} is missing from git history; cannot verify schema and migration immutability.",
            )
        return clean_base, None

    if clean_base and git_object_exists(repo_root, f"{clean_base}^{{commit}}"):
        return clean_base, None

    parent = run_git(repo_root, ["rev-parse", "--verify", "HEAD^"])
    if parent.returncode == 0:
        resolved = parent.stdout.strip()
        if resolved and git_object_exists(repo_root, f"{resolved}^{{commit}}"):
            return resolved, None
    return None, None


def get_base_migrations(repo_root: str, base_ref: str | None) -> dict[str, str]:
    if not base_ref:
        return {}
    res = run_git(
        repo_root,
        ["ls-tree", "-r", "--full-tree", base_ref, "--", "server/prisma/migrations"],
    )
    if res.returncode != 0:
        return {}
    migrations: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        meta, rel_path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob" and rel_path.endswith("/migration.sql"):
            migrations[rel_path] = parts[2]
    return migrations


def check_migration_immutability(repo_root: str, base_ref: str | None) -> list[str]:
    errors: list[str] = []
    base_migrations = get_base_migrations(repo_root, base_ref)
    for rel_path, expected_sha in sorted(base_migrations.items()):
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(abs_path):
            errors.append(
                f"Existing migration from base branch cannot be deleted or renamed: {rel_path}"
            )
            continue
        with open(abs_path, "rb") as fh:
            actual_sha = git_blob_sha(fh.read())
        if actual_sha != expected_sha:
            errors.append(
                f"Existing migration from base branch is immutable and cannot be modified: {rel_path}"
            )
    return errors


def strip_sql_comments(sql_text: str) -> str:
    no_block = COMMENT_BLOCK_RE.sub(" ", sql_text)
    no_line = SQL_LINE_COMMENT_RE.sub(" ", no_block)
    return no_line


def has_executable_sql(sql_text: str) -> bool:
    stripped = strip_sql_comments(sql_text)
    remainder = re.sub(r"[\s;]+", "", stripped)
    return bool(re.search(r"[A-Za-z0-9_]", remainder))


def strip_js_comments(source: str) -> str:
    no_block = COMMENT_BLOCK_RE.sub(" ", source)
    return JS_LINE_COMMENT_RE.sub(" ", no_block)


def validate_migrations(repo_root: str) -> tuple[list[str], int]:
    errors: list[str] = []
    migrations_dir = os.path.join(repo_root, "server/prisma/migrations")
    if not os.path.isdir(migrations_dir):
        errors.append("server/prisma/migrations/ directory must exist")
        return errors, 0

    lock_path = os.path.join(migrations_dir, "migration_lock.toml")
    if not os.path.isfile(lock_path) or os.path.getsize(lock_path) == 0:
        errors.append("server/prisma/migrations/migration_lock.toml must exist and be non-empty")
    else:
        with open(lock_path, encoding="utf-8") as fh:
            providers: list[str] = []
            for raw_line in fh:
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                match = LOCK_PROVIDER_RE.match(line)
                if match:
                    providers.append(match.group(2).strip())
        if providers != ["postgresql"]:
            errors.append(
                f"server/prisma/migrations/migration_lock.toml must configure provider = \"postgresql\" (found: {providers or 'none'})"
            )

    found_migrations: list[str] = []
    for root_dir, _dirs, files in os.walk(migrations_dir):
        for fname in files:
            if fname != "migration.sql":
                continue
            abs_file = os.path.join(root_dir, fname)
            rel_to_migrations = os.path.relpath(abs_file, migrations_dir)
            parts = rel_to_migrations.split(os.sep)
            repo_rel = os.path.join("server/prisma/migrations", rel_to_migrations).replace(os.sep, "/")
            if len(parts) != 2 or not parts[0].strip() or parts[0].startswith("."):
                errors.append(
                    f"Migration file must reside directly inside a valid migration subdirectory: {repo_rel}"
                )
                continue
            found_migrations.append(repo_rel)
            with open(abs_file, encoding="utf-8") as fh:
                content = fh.read()
            if not content.strip():
                errors.append(f"Migration SQL file cannot be empty: {repo_rel}")
            elif not has_executable_sql(content):
                errors.append(
                    f"Migration SQL file cannot contain only comments or semicolons: {repo_rel}"
                )

    if not found_migrations:
        errors.append(
            "server/prisma/migrations/ must contain at least one valid <migration>/migration.sql file"
        )

    return errors, len(found_migrations)


def validate_database_test_files(repo_root: str) -> tuple[list[str], int]:
    errors: list[str] = []
    test_dir = os.path.join(repo_root, "server/src/__tests__/database")
    if not os.path.isdir(test_dir):
        errors.append("server/src/__tests__/database/ directory must exist when schema.prisma is present")
        return errors, 0

    test_files = sorted(glob.glob(os.path.join(test_dir, "*.test.ts")))
    if not test_files:
        errors.append("server/src/__tests__/database/ must contain at least one *.test.ts file")
        return errors, 0

    runnable_files = 0
    for abs_path in test_files:
        rel_path = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
        with open(abs_path, encoding="utf-8") as fh:
            raw = fh.read()
        if not raw.strip():
            errors.append(f"Database test file cannot be empty: {rel_path}")
            continue
        cleaned = strip_js_comments(raw)
        if not RUNNABLE_TEST_RE.search(cleaned):
            errors.append(
                f"Database test file must contain at least one runnable test() or it() case: {rel_path}"
            )
            continue
        runnable_files += 1

    return errors, runnable_files


def split_shell_chain(command: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Split a shell command string on &&, ||, ; outside quotes."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    tokens = list(lexer)

    segments: list[tuple[str, list[str]]] = []
    errors: list[str] = []
    current: list[str] = []
    prev_op = ""

    for tok in tokens:
        if tok in {"&&", ";", "||"}:
            if not current:
                errors.append(f"Invalid empty command segment near operator '{tok}'")
            else:
                segments.append((prev_op, current))
                current = []
            prev_op = tok
        else:
            current.append(tok)

    if current:
        segments.append((prev_op, current))
    elif tokens:
        errors.append("Script command ends with a dangling shell operator")

    return segments, errors


def unwrap_command(tokens: list[str]) -> tuple[str, list[str]]:
    idx = 0
    while idx < len(tokens) and ENV_ASSIGN_RE.match(tokens[idx]):
        idx += 1
    if idx >= len(tokens):
        return "", []

    cmd = os.path.basename(tokens[idx])
    rest = tokens[idx + 1 :]

    if cmd in WRAPPER_EXECUTABLES:
        j = 0
        while j < len(rest) and rest[j].startswith("-"):
            j += 1
        if j < len(rest):
            return os.path.basename(rest[j]), rest[j + 1 :]
        return cmd, rest

    if cmd in {"npm", "pnpm"} and rest and rest[0] == "exec":
        args_after = [a for a in rest[1:] if a != "--"]
        j = 0
        while j < len(args_after) and args_after[j].startswith("-"):
            j += 1
        if j < len(args_after):
            return os.path.basename(args_after[j]), args_after[j + 1 :]

    return cmd, rest


def has_tap_reporter(args: list[str]) -> bool:
    for idx, arg in enumerate(args):
        if arg == "--test-reporter=tap":
            return True
        if arg == "--test-reporter" and idx + 1 < len(args) and args[idx + 1] == "tap":
            return True
    return False


def validate_scripts(repo_root: str) -> list[str]:
    errors: list[str] = []
    pkg_path = os.path.join(repo_root, "server/package.json")
    if not os.path.isfile(pkg_path):
        return ["server/package.json must exist"]

    with open(pkg_path, encoding="utf-8") as fh:
        scripts = json.load(fh).get("scripts") or {}

    required = ("db:validate", "db:migrate:deploy", "db:seed", "test:db")
    for name in required:
        raw_cmd = scripts.get(name)
        if not isinstance(raw_cmd, str) or not raw_cmd.strip():
            errors.append(f"server/package.json scripts.{name} is missing or empty")
            continue

        try:
            segments, parse_errors = split_shell_chain(raw_cmd)
        except ValueError as exc:
            errors.append(f"server/package.json scripts.{name} cannot be parsed: {exc}")
            continue

        if parse_errors:
            errors.extend(f"server/package.json scripts.{name}: {e}" for e in parse_errors)
            continue

        semantic_match = False
        blocked_script = False

        for prev_op, tokens in segments:
            exe, args = unwrap_command(tokens)
            if not exe:
                errors.append(f"server/package.json scripts.{name} contains an empty command")
                blocked_script = True
                continue

            if prev_op == "||" and (
                exe in PLACEHOLDER_COMMANDS
                or (exe == "exit" and (not args or args[0] == "0"))
            ):
                errors.append(
                    f"server/package.json scripts.{name} masks failures with '|| {exe}'"
                )
                blocked_script = True
                continue

            if exe in PLACEHOLDER_COMMANDS or (exe == "exit"):
                errors.append(
                    f"server/package.json scripts.{name} uses disallowed placeholder command '{exe}'"
                )
                blocked_script = True
                continue

            if name == "db:validate":
                if exe == "prisma" and "validate" in args:
                    semantic_match = True
            elif name == "db:migrate:deploy":
                if exe == "prisma" and "migrate" in args and "deploy" in args:
                    semantic_match = True
            elif name == "db:seed":
                if exe == "prisma" and len(args) >= 2 and args[0] == "db" and args[1] == "seed":
                    semantic_match = True
                elif exe in JS_RUNNERS and any(
                    re.search(r"(?:^|/)(?:prisma/)?seed(?:\.[cm]?[jt]s)?$", a) for a in args
                ):
                    semantic_match = True
            elif name == "test:db":
                joined_args = " ".join(args)
                if exe == "npm" and ("test" in args or "run" in args):
                    errors.append(
                        "server/package.json scripts.test:db cannot call generic 'npm test'"
                    )
                    blocked_script = True
                    continue
                if "src/__tests__/*.test.ts" in joined_args or "health.test.ts" in joined_args:
                    errors.append(
                        "server/package.json scripts.test:db must target src/__tests__/database/, not generic unit tests"
                    )
                    blocked_script = True
                    continue
                is_runner = (exe == "tsx" and "--test" in args) or (
                    exe == "node" and "--test" in args
                )
                targets_db_dir = any("src/__tests__/database" in a for a in args)
                if is_runner and targets_db_dir and has_tap_reporter(args):
                    semantic_match = True

        if not blocked_script and not semantic_match:
            if name == "db:validate":
                errors.append("server/package.json scripts.db:validate must execute 'prisma validate'")
            elif name == "db:migrate:deploy":
                errors.append(
                    "server/package.json scripts.db:migrate:deploy must execute 'prisma migrate deploy'"
                )
            elif name == "db:seed":
                errors.append(
                    "server/package.json scripts.db:seed must execute Prisma db seed or a seed script (seed.ts)"
                )
            elif name == "test:db":
                errors.append(
                    "server/package.json scripts.test:db must invoke node/tsx --test with --test-reporter=tap targeting src/__tests__/database/"
                )

    return errors


def write_github_output(path: str | None, key: str, value: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def cmd_check_schema_and_contract(args: argparse.Namespace) -> int:
    repo_root = os.path.abspath(args.repo_root)
    base_ref, base_err = resolve_base_ref(repo_root, args.event_name, args.base_sha)
    if base_err:
        print(f"::error::{base_err}")
        return 1

    base_has_schema = bool(
        base_ref and git_object_exists(repo_root, f"{base_ref}:server/prisma/schema.prisma")
    )
    schema_path = os.path.join(repo_root, "server/prisma/schema.prisma")
    pr_has_schema = os.path.isfile(schema_path)

    print(
        "Database schema detection: "
        f"EVENT_NAME={args.event_name}, BASE_REF={base_ref or 'none'}, "
        f"BASE_HAS_SCHEMA={str(base_has_schema).lower()}, PR_HAS_SCHEMA={str(pr_has_schema).lower()}"
    )

    if base_has_schema and not pr_has_schema:
        print(
            "::error::server/prisma/schema.prisma exists on base branch and cannot be deleted to bypass Database Integration checks."
        )
        write_github_output(args.github_output, "run_prisma", "false")
        return 1

    immutability_errors = check_migration_immutability(repo_root, base_ref)

    if not pr_has_schema:
        if immutability_errors:
            for err in immutability_errors:
                print(f"::error::{err}")
            write_github_output(args.github_output, "run_prisma", "false")
            return 1
        print(
            "server/prisma/schema.prisma is not present on base or head yet; "
            "Prisma validate, migrate deploy, seed, and test:db are skipped (N/A) until SBS-19 lands."
        )
        write_github_output(args.github_output, "run_prisma", "false")
        return 0

    errors: list[str] = []
    errors.extend(immutability_errors)

    with open(schema_path, encoding="utf-8") as fh:
        if not fh.read().strip():
            errors.append("server/prisma/schema.prisma must be non-empty")

    mig_errors, mig_count = validate_migrations(repo_root)
    errors.extend(mig_errors)

    seed_path = os.path.join(repo_root, "server/prisma/seed.ts")
    if not os.path.isfile(seed_path):
        errors.append("server/prisma/seed.ts must exist")
    else:
        with open(seed_path, encoding="utf-8") as fh:
            if not fh.read().strip():
                errors.append("server/prisma/seed.ts must be non-empty")

    db_test_errors, test_file_count = validate_database_test_files(repo_root)
    errors.extend(db_test_errors)

    errors.extend(validate_scripts(repo_root))

    if errors:
        for err in errors:
            print(f"::error::{err}")
        write_github_output(args.github_output, "run_prisma", "false")
        return 1

    print(
        f"Verified SBS-19 database contract: {mig_count} valid migration(s), "
        f"{test_file_count} runnable database test file(s), migration immutability intact, and all scripts valid."
    )
    write_github_output(args.github_output, "run_prisma", "true")
    return 0


def cmd_verify_tap(args: argparse.Namespace) -> int:
    if not os.path.isfile(args.tap_file):
        print(f"::error::TAP output file does not exist: {args.tap_file}")
        return 1

    with open(args.tap_file, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    if not lines:
        print("::error::Database test runner produced empty TAP output.")
        return 1

    counters: dict[str, int] = {}
    ok_lines = 0
    not_ok_lines = 0
    metric_re = re.compile(r"^#\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$")

    for line in lines:
        match = metric_re.match(line.strip())
        if match:
            counters[match.group(1)] = int(match.group(2))
        if line.startswith("ok "):
            ok_lines += 1
        elif line.startswith("not ok "):
            not_ok_lines += 1

    errors: list[str] = []
    tests = counters.get("tests")
    passed = counters.get("pass")
    failed = counters.get("fail")
    cancelled = counters.get("cancelled", 0)
    skipped = counters.get("skipped", 0)

    if tests is None or passed is None or failed is None:
        errors.append("TAP output missing required Node test summary diagnostics (# tests, # pass, # fail)")
    else:
        if tests <= 0:
            errors.append(f"Database test suite must execute at least 1 test (reported # tests {tests})")
        if passed <= 0:
            errors.append(f"Database test suite must pass at least 1 test (reported # pass {passed})")
        if failed > 0:
            errors.append(f"Database test suite reported {failed} failing test(s)")
        if cancelled > 0:
            errors.append(f"Database test suite reported {cancelled} cancelled test(s)")
        if tests > 0 and skipped >= tests:
            errors.append("Database test suite skipped every test; at least one test must pass")

    if not_ok_lines > 0:
        errors.append(f"TAP output contains {not_ok_lines} 'not ok' result line(s)")
    if ok_lines == 0:
        errors.append("TAP output does not contain any passing top-level 'ok' test results")

    if errors:
        for err in errors:
            print(f"::error::{err}")
        return 1

    print(
        f"Verified TAP database test results: tests={tests}, pass={passed}, fail={failed}, "
        f"cancelled={cancelled}, skipped={skipped}."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CI validator for SBS-19 database contract")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_p = subparsers.add_parser("check-schema-and-contract")
    check_p.add_argument("--repo-root", default=".")
    check_p.add_argument("--event-name", required=True)
    check_p.add_argument("--base-sha", default="")
    check_p.add_argument("--github-output", default="")
    check_p.set_defaults(func=cmd_check_schema_and_contract)

    tap_p = subparsers.add_parser("verify-tap")
    tap_p.add_argument("--tap-file", required=True)
    tap_p.set_defaults(func=cmd_verify_tap)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
