#!/usr/bin/env python3
"""Fail-closed CI validator for SBS-19 Prisma schema, migrations, script contract, and TAP output."""

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


FORBIDDEN_SHELL_RE = re.compile(r"[;|&><`$(){}\\\n\r\0]")
ENV_ASSIGN_LIKE_RE = re.compile(r"^([^=\s]+)=(.*)$")
SAFE_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ZERO_SHA_RE = re.compile(r"^0+$")
CANONICAL_SCHEMA_PATHS = frozenset({"prisma/schema.prisma"})
PRISMA_CONFIG_CANDIDATES = (
    "prisma.config.ts",
    "prisma.config.js",
    "prisma.config.mjs",
    "prisma.config.cjs",
    "server/prisma.config.ts",
    "server/prisma.config.js",
    "server/prisma.config.mjs",
    "server/prisma.config.cjs",
)
SAFE_SEED_PATH_RE = re.compile(r"^(?:\./)?(?:prisma/)?seed\.[cm]?[jt]s$")
SAFE_DB_TEST_PATH_RE = re.compile(
    r"^(?:\./)?src/__tests__/database(?:/|/(?:\*|[A-Za-z0-9_.-]+)\.test\.ts)?$"
)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")
JS_LINE_COMMENT_RE = re.compile(r"//[^\r\n]*")
RUNNABLE_TEST_RE = re.compile(r"(?<![.\w])(?:test|it)\s*\(")
LOCK_PROVIDER_RE = re.compile(r"""^\s*provider\s*=\s*(["'])([^"']+)\1\s*$""")


class GitInspectionError(RuntimeError):
    """Raised when inspecting base Git state fails."""


def run_git(repo_root: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def git_object_exists(repo_root: str, rev_spec: str) -> bool:
    try:
        res = run_git(repo_root, ["cat-file", "-e", rev_spec])
    except OSError as exc:
        raise GitInspectionError("Failed to execute git cat-file while inspecting base commit.") from exc
    return res.returncode == 0


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def validate_commit_ref(repo_root: str, candidate: str, source_label: str) -> tuple[str | None, str | None]:
    if not candidate:
        return None, f"{source_label} is empty; cannot verify schema and migration immutability."
    if ZERO_SHA_RE.match(candidate):
        return None, f"{source_label} is an invalid zero commit SHA; cannot verify migration immutability."
    try:
        exists = git_object_exists(repo_root, f"{candidate}^{{commit}}")
    except GitInspectionError as exc:
        return None, str(exc)
    if not exists:
        return (
            None,
            f"Base commit {candidate} ({source_label}) is missing from git history; cannot verify schema and migration immutability.",
        )
    return candidate, None


def resolve_base_ref(
    repo_root: str, event_name: str, base_sha: str | None
) -> tuple[str | None, str | None]:
    clean_base = (base_sha or "").strip()
    if event_name == "pull_request":
        return validate_commit_ref(repo_root, clean_base, "pull_request base SHA")

    if event_name == "push":
        return validate_commit_ref(repo_root, clean_base, "push before SHA")

    if event_name == "workflow_dispatch":
        if clean_base:
            return validate_commit_ref(repo_root, clean_base, "workflow_dispatch base SHA")
        try:
            parent = run_git(repo_root, ["rev-parse", "--verify", "HEAD^"])
        except OSError:
            return None, "Failed to execute git rev-parse HEAD^ during workflow_dispatch base resolution."
        if parent.returncode != 0:
            return (
                None,
                f"git rev-parse --verify HEAD^ failed during workflow_dispatch base resolution (exit code {parent.returncode}).",
            )
        resolved = parent.stdout.strip()
        return validate_commit_ref(repo_root, resolved, "workflow_dispatch HEAD^")

    return (
        None,
        f"Unsupported or missing GitHub event '{event_name}'; cannot safely resolve base commit for migration immutability.",
    )


def get_base_migrations(repo_root: str, base_ref: str) -> dict[str, str]:
    if not isinstance(base_ref, str) or not base_ref.strip():
        raise GitInspectionError("Base commit ref is required for migration immutability inspection.")
    try:
        res = run_git(
            repo_root,
            ["ls-tree", "-r", "--full-tree", base_ref, "--", "server/prisma/migrations"],
        )
    except OSError as exc:
        raise GitInspectionError(
            "Failed to execute git ls-tree while inspecting base migrations."
        ) from exc

    if res.returncode != 0:
        raise GitInspectionError(
            f"git ls-tree failed while inspecting base migrations (exit code {res.returncode})."
        )

    migrations: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            raise GitInspectionError(
                "Unexpected output format from git ls-tree while inspecting base migrations."
            )
        meta, rel_path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 3:
            raise GitInspectionError("Malformed git ls-tree entry while inspecting base migrations.")
        if parts[1] == "blob" and rel_path.endswith("/migration.sql"):
            migrations[rel_path] = parts[2]
    return migrations


def check_migration_immutability(repo_root: str, base_ref: str) -> list[str]:
    try:
        base_migrations = get_base_migrations(repo_root, base_ref)
    except GitInspectionError as exc:
        return [str(exc)]

    errors: list[str] = []
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
    return SQL_LINE_COMMENT_RE.sub(" ", no_block)


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


def validate_exact_executable_token(token: str, script_name: str, role: str = "executable") -> str | None:
    if not token or token in {".", ".."}:
        return f"server/package.json scripts.{script_name} has invalid {role} token"
    if "/" in token or "\\" in token:
        return (
            f"server/package.json scripts.{script_name} cannot use a path-qualified {role} token"
        )
    if "=" in token or token.startswith("-"):
        return f"server/package.json scripts.{script_name} has invalid {role} token"
    return None


def describe_env_var_name(raw_name: str) -> str:
    return f"'{raw_name}'" if SAFE_VAR_NAME_RE.match(raw_name) else "<invalid>"


def parse_single_direct_command(script_name: str, raw_cmd: object) -> tuple[str | None, list[str], str | None]:
    """Parse one direct local executable command without wrappers, shell chaining, or unsafe env vars."""
    if not isinstance(raw_cmd, str) or not raw_cmd.strip():
        return None, [], f"server/package.json scripts.{script_name} is missing or empty"

    if FORBIDDEN_SHELL_RE.search(raw_cmd):
        return (
            None,
            [],
            f"server/package.json scripts.{script_name} contains disallowed shell chaining, redirection, or substitution syntax",
        )

    try:
        tokens = shlex.split(raw_cmd, posix=True)
    except ValueError as exc:
        return None, [], f"server/package.json scripts.{script_name} cannot be parsed: {exc}"

    if not tokens:
        return None, [], f"server/package.json scripts.{script_name} is empty"

    for tok in tokens:
        if tok.startswith("~"):
            return (
                None,
                [],
                f"server/package.json scripts.{script_name} contains disallowed home-directory expansion",
            )

    idx = 0
    seen_env = False
    while idx < len(tokens):
        env_match = ENV_ASSIGN_LIKE_RE.match(tokens[idx])
        if not env_match:
            break
        var_name = env_match.group(1)
        safe_var = describe_env_var_name(var_name)

        if script_name != "test:db":
            return (
                None,
                [],
                f"server/package.json scripts.{script_name} does not allow environment assignment {safe_var}",
            )
        if seen_env:
            return (
                None,
                [],
                f"server/package.json scripts.{script_name} does not allow repeated environment assignment {safe_var}",
            )
        if tokens[idx] != "NODE_ENV=test":
            return (
                None,
                [],
                f"server/package.json scripts.{script_name} rejected disallowed environment variable {safe_var}; only NODE_ENV=test is permitted",
            )
        seen_env = True
        idx += 1

    if idx >= len(tokens):
        return (
            None,
            [],
            f"server/package.json scripts.{script_name} contains only an environment assignment without a command",
        )

    remaining = tokens[idx:]
    first = remaining[0]
    first_err = validate_exact_executable_token(first, script_name, role="executable")
    if first_err:
        return None, [], first_err

    if first in {"npx", "npm"}:
        return (
            None,
            [],
            f"server/package.json scripts.{script_name} cannot invoke '{first}' wrapper; use the direct local executable from workspace dependencies",
        )

    return first, remaining[1:], None


def consume_canonical_prisma_schema_flag(args: list[str]) -> tuple[list[str], str | None]:
    """Allow omitted --schema or exact canonical prisma/schema.prisma; reject alternates and --config."""
    out: list[str] = []
    seen_schema = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--config" or arg.startswith("--config="):
            return [], "--config option is not permitted because it can redirect Prisma schema or migrations outside server/prisma/"
        if arg.startswith("--schema="):
            if seen_schema:
                return [], "Duplicate --schema flag is not allowed"
            val = arg.split("=", 1)[1]
            if val not in CANONICAL_SCHEMA_PATHS:
                return (
                    [],
                    f"Non-canonical --schema path is rejected (expected 'prisma/schema.prisma', got: {val!r})",
                )
            seen_schema = True
            i += 1
        elif arg == "--schema":
            if seen_schema:
                return [], "Duplicate --schema flag is not allowed"
            if i + 1 >= len(args):
                return [], "Empty or missing value for --schema option"
            val = args[i + 1]
            if val not in CANONICAL_SCHEMA_PATHS:
                return (
                    [],
                    f"Non-canonical --schema path is rejected (expected 'prisma/schema.prisma', got: {val!r})",
                )
            seen_schema = True
            i += 2
        else:
            out.append(arg)
            i += 1
    return out, None


def validate_db_validate_script(exe: str, args: list[str]) -> str | None:
    if exe != "prisma":
        return "server/package.json scripts.db:validate must directly invoke exact executable 'prisma validate'"
    core_args, err = consume_canonical_prisma_schema_flag(args)
    if err:
        return f"server/package.json scripts.db:validate: {err}"
    if core_args != ["validate"]:
        return "server/package.json scripts.db:validate must strictly run 'prisma validate' without extra commands or flags"
    return None


def validate_db_migrate_deploy_script(exe: str, args: list[str]) -> str | None:
    if exe != "prisma":
        return "server/package.json scripts.db:migrate:deploy must directly invoke exact executable 'prisma migrate deploy'"
    core_args, err = consume_canonical_prisma_schema_flag(args)
    if err:
        return f"server/package.json scripts.db:migrate:deploy: {err}"
    if core_args != ["migrate", "deploy"]:
        return "server/package.json scripts.db:migrate:deploy must strictly run 'prisma migrate deploy' without extra commands or flags"
    return None


def validate_seed_runner_command(exe: str, args: list[str]) -> bool:
    if exe == "tsx":
        return len(args) == 1 and bool(SAFE_SEED_PATH_RE.match(args[0]))
    if exe == "node":
        idx = 0
        if idx < len(args):
            if args[idx] == "--import=tsx":
                idx += 1
            elif args[idx] == "--import" and idx + 1 < len(args) and args[idx + 1] == "tsx":
                idx += 2
        remaining = args[idx:]
        return len(remaining) == 1 and bool(SAFE_SEED_PATH_RE.match(remaining[0]))
    return False


def validate_db_seed_script(exe: str, args: list[str]) -> str | None:
    if exe == "prisma":
        core_args, err = consume_canonical_prisma_schema_flag(args)
        if err:
            return f"server/package.json scripts.db:seed: {err}"
        if core_args == ["db", "seed"]:
            return None
        return "server/package.json scripts.db:seed using prisma must strictly run 'prisma db seed'"

    if exe in {"tsx", "node"}:
        if validate_seed_runner_command(exe, args):
            return None
        return f"server/package.json scripts.db:seed using {exe} must strictly target prisma/seed.ts or seed.ts without extra commands or flags"

    return "server/package.json scripts.db:seed must directly invoke exact executable 'prisma', 'tsx', or 'node'"


def validate_test_db_script(exe: str, args: list[str]) -> str | None:
    if exe not in {"node", "tsx"}:
        return (
            "server/package.json scripts.test:db must directly invoke exact executable 'node' or 'tsx' "
            "targeting src/__tests__/database/*.test.ts with --test-reporter=tap"
        )

    saw_tsx_import = exe == "tsx"
    saw_test_flag = False
    saw_tap_reporter = False
    targets: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if exe == "node" and arg == "--import=tsx":
            if saw_tsx_import:
                return "server/package.json scripts.test:db: duplicate --import=tsx"
            saw_tsx_import = True
            i += 1
        elif exe == "node" and arg == "--import":
            if saw_tsx_import or i + 1 >= len(args) or args[i + 1] != "tsx":
                return "server/package.json scripts.test:db: --import must strictly specify 'tsx'"
            saw_tsx_import = True
            i += 2
        elif arg == "--test":
            saw_test_flag = True
            i += 1
        elif arg == "--test-reporter=tap":
            if saw_tap_reporter:
                return "server/package.json scripts.test:db: duplicate --test-reporter"
            saw_tap_reporter = True
            i += 1
        elif arg == "--test-reporter":
            if saw_tap_reporter or i + 1 >= len(args) or args[i + 1] != "tap":
                return "server/package.json scripts.test:db: --test-reporter must strictly be 'tap'"
            saw_tap_reporter = True
            i += 2
        elif arg.startswith("-"):
            return f"server/package.json scripts.test:db uses unsupported option '{arg}'"
        else:
            targets.append(arg)
            i += 1

    if not saw_tsx_import:
        return "server/package.json scripts.test:db must include '--import tsx' when invoking node"
    if not saw_test_flag:
        return "server/package.json scripts.test:db must include '--test'"
    if not saw_tap_reporter:
        return "server/package.json scripts.test:db must include '--test-reporter=tap'"
    if not targets:
        return "server/package.json scripts.test:db must explicitly target src/__tests__/database/*.test.ts"

    for target in targets:
        if not SAFE_DB_TEST_PATH_RE.match(target):
            return (
                f"server/package.json scripts.test:db target '{target}' must point strictly to src/__tests__/database/"
            )

    return None


SCRIPT_VALIDATORS = {
    "db:validate": validate_db_validate_script,
    "db:migrate:deploy": validate_db_migrate_deploy_script,
    "db:seed": validate_db_seed_script,
    "test:db": validate_test_db_script,
}


def validate_prisma_config(repo_root: str) -> list[str]:
    """Conservative guard preventing Prisma configuration from redirecting schema or migrations."""
    errors: list[str] = []

    for rel_path in PRISMA_CONFIG_CANDIDATES:
        if os.path.exists(os.path.join(repo_root, rel_path)):
            errors.append(
                f"Prisma config file '{rel_path}' is not permitted because schema and migrations must use canonical server/prisma/ paths"
            )

    root_pkg_path = os.path.join(repo_root, "package.json")
    if os.path.isfile(root_pkg_path):
        with open(root_pkg_path, encoding="utf-8") as fh:
            root_pkg = json.load(fh)
        if "prisma" in root_pkg:
            errors.append(
                "Root package.json cannot define a 'prisma' configuration block; place canonical Prisma configuration in server/package.json"
            )

    server_pkg_path = os.path.join(repo_root, "server/package.json")
    if os.path.isfile(server_pkg_path):
        with open(server_pkg_path, encoding="utf-8") as fh:
            server_pkg = json.load(fh)
        if "prisma" in server_pkg:
            prisma_cfg = server_pkg["prisma"]
            if not isinstance(prisma_cfg, dict):
                errors.append("server/package.json 'prisma' field must be an object")
            else:
                unknown_keys = sorted(set(prisma_cfg.keys()) - {"schema", "seed"})
                if unknown_keys:
                    errors.append(
                        f"server/package.json 'prisma' contains unsupported key(s) {unknown_keys}; only 'schema' and 'seed' are allowed"
                    )
                if "schema" in prisma_cfg and prisma_cfg["schema"] not in CANONICAL_SCHEMA_PATHS:
                    errors.append(
                        f"server/package.json prisma.schema must equal 'prisma/schema.prisma' (got: {prisma_cfg['schema']!r})"
                    )
                if "seed" in prisma_cfg:
                    exe, args, parse_err = parse_single_direct_command("prisma.seed", prisma_cfg["seed"])
                    if parse_err:
                        errors.append(parse_err)
                    elif exe is None or not validate_seed_runner_command(exe, args):
                        errors.append(
                            "server/package.json prisma.seed must directly execute 'tsx' or 'node' targeting prisma/seed.ts without wrappers"
                        )

    return errors


def validate_scripts(repo_root: str) -> list[str]:
    errors: list[str] = []
    pkg_path = os.path.join(repo_root, "server/package.json")
    if not os.path.isfile(pkg_path):
        return ["server/package.json must exist"]

    with open(pkg_path, encoding="utf-8") as fh:
        scripts = json.load(fh).get("scripts") or {}

    for name, validator in SCRIPT_VALIDATORS.items():
        exe, args, parse_err = parse_single_direct_command(name, scripts.get(name))
        if parse_err:
            errors.append(parse_err)
            continue
        assert exe is not None
        semantic_err = validator(exe, args)
        if semantic_err:
            errors.append(semantic_err)

    return errors


def write_github_output(path: str | None, key: str, value: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def cmd_check_schema_and_contract(args: argparse.Namespace) -> int:
    repo_root = os.path.abspath(args.repo_root)
    base_ref, base_err = resolve_base_ref(repo_root, args.event_name, args.base_sha)
    if base_err or not base_ref:
        print(f"::error::{base_err or 'Unable to resolve base commit reference.'}")
        write_github_output(args.github_output, "run_prisma", "false")
        return 1

    try:
        base_has_schema = git_object_exists(repo_root, f"{base_ref}:server/prisma/schema.prisma")
    except GitInspectionError as exc:
        print(f"::error::{exc}")
        write_github_output(args.github_output, "run_prisma", "false")
        return 1

    schema_path = os.path.join(repo_root, "server/prisma/schema.prisma")
    pr_has_schema = os.path.isfile(schema_path)

    print(
        "Database schema detection: "
        f"EVENT_NAME={args.event_name}, BASE_REF={base_ref}, "
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
    errors.extend(validate_prisma_config(repo_root))

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
        f"{test_file_count} runnable database test file(s), canonical paths and immutability intact."
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


def render_step_summary(
    *,
    validator_tests_outcome: str,
    pg_health_outcome: str,
    pg_connect_outcome: str,
    contract_outcome: str,
    run_prisma: str,
    prisma_outcome: str,
) -> str:
    """Render precise 5-row GitHub Actions Step Summary table separating self-tests from SBS-19 contract."""
    infra_outcomes = {pg_health_outcome, pg_connect_outcome}
    if infra_outcomes == {"success"}:
        infra_status = "PASS"
        infra_note = "Container healthy, host connection, pg_isready, SELECT 1"
    elif "failure" in infra_outcomes:
        infra_status = "FAIL"
        infra_note = f"PostgreSQL check failed (health={pg_health_outcome}, connect={pg_connect_outcome})"
    elif infra_outcomes <= {"skipped", ""}:
        infra_status = "SKIPPED"
        infra_note = "PostgreSQL checks were skipped because an earlier step failed"
    else:
        infra_status = "NOT COMPLETED"
        infra_note = f"PostgreSQL checks did not finish (health={pg_health_outcome}, connect={pg_connect_outcome})"

    if validator_tests_outcome == "success":
        self_test_status = "PASS"
        self_test_note = "Validator regression tests passed"
    elif validator_tests_outcome == "failure":
        self_test_status = "FAIL"
        self_test_note = "Validator self-tests failed"
    elif validator_tests_outcome in {"skipped", ""}:
        self_test_status = "SKIPPED"
        self_test_note = "Validator self-tests were skipped"
    else:
        self_test_status = "NOT COMPLETED"
        self_test_note = f"Validator self-tests did not complete ({validator_tests_outcome})"

    if contract_outcome == "success" and run_prisma == "false":
        contract_status = "N/A"
        contract_note = "Awaiting SBS-19 schema and database artifacts; baseline inspection completed"
    elif contract_outcome == "success" and run_prisma == "true":
        contract_status = "PASS"
        contract_note = "Canonical schema, migration, and script contract validated"
    elif contract_outcome == "failure":
        contract_status = "FAIL"
        contract_note = "Schema, migration immutability, base ref, or script contract check failed"
    else:
        contract_status = "NOT COMPLETED"
        contract_note = f"Contract inspection did not complete (outcome={contract_outcome}, run_prisma={run_prisma or 'unset'})"

    if contract_outcome == "success" and run_prisma == "false":
        prisma_status = "N/A"
        prisma_note = "Application schema is not available yet"
    elif contract_outcome == "success" and run_prisma == "true" and prisma_outcome == "success":
        prisma_status = "PASS"
        prisma_note = "Validate, migration deploy, seed, and database tests passed"
    elif prisma_outcome == "failure":
        prisma_status = "FAIL"
        prisma_note = "Prisma validate, migration deploy, seed, or database tests failed"
    else:
        prisma_status = "NOT COMPLETED"
        prisma_note = f"Prisma application suite did not complete (contract={contract_outcome}, prisma={prisma_outcome})"

    if (
        infra_status == "PASS"
        and self_test_status == "PASS"
        and contract_status == "N/A"
        and prisma_status == "N/A"
    ):
        overall_status = "SUCCESS"
        overall_note = "All applicable baseline checks passed"
    elif (
        infra_status == "PASS"
        and self_test_status == "PASS"
        and contract_status == "PASS"
        and prisma_status == "PASS"
    ):
        overall_status = "SUCCESS"
        overall_note = "All applicable database integration checks passed"
    else:
        overall_status = "FAILURE"
        overall_note = "One or more required Database Integration checks failed or did not complete"

    lines = [
        "## Database Integration Coverage",
        "",
        "| Area | Status | Keterangan |",
        "|---|---|---|",
        f"| PostgreSQL infrastructure | {infra_status} | {infra_note} |",
        f"| CI validator self-tests | {self_test_status} | {self_test_note} |",
        f"| SBS-19 schema/script/migration contract | {contract_status} | {contract_note} |",
        f"| Prisma application integration | {prisma_status} | {prisma_note} |",
        f"| Overall Database Integration | {overall_status} | {overall_note} |",
        "",
    ]
    return "\n".join(lines)


def cmd_write_summary(args: argparse.Namespace) -> int:
    markdown = render_step_summary(
        validator_tests_outcome=args.validator_tests_outcome,
        pg_health_outcome=args.pg_health_outcome,
        pg_connect_outcome=args.pg_connect_outcome,
        contract_outcome=args.contract_outcome,
        run_prisma=args.run_prisma,
        prisma_outcome=args.prisma_outcome,
    )
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(markdown)
    print(markdown)
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

    sum_p = subparsers.add_parser("write-summary")
    sum_p.add_argument("--summary-file", default="")
    sum_p.add_argument("--validator-tests-outcome", required=True)
    sum_p.add_argument("--pg-health-outcome", required=True)
    sum_p.add_argument("--pg-connect-outcome", required=True)
    sum_p.add_argument("--contract-outcome", required=True)
    sum_p.add_argument("--run-prisma", default="")
    sum_p.add_argument("--prisma-outcome", required=True)
    sum_p.set_defaults(func=cmd_write_summary)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
