#!/usr/bin/env python3
"""Fail-closed CI validator for SBS-19 Prisma 7.10.1 config, version pin, migrations, script contract, and TAP output."""

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


CANONICAL_PRISMA_VERSION = "7.10.1"
CANONICAL_CONFIG_REL_PATH = "server/prisma7.config.ts"
CANONICAL_SCHEMA_REL_PATH = "server/prisma/schema.prisma"
CANONICAL_SEED_REL_PATH = "server/prisma/seed.ts"
CANONICAL_MIGRATIONS_REL_DIR = "server/prisma/migrations"
CANONICAL_SCHEMA_PATHS = frozenset({"prisma/schema.prisma"})

PRISMA_CONFIG_EXTENSIONS = (".js", ".ts", ".mjs", ".cjs", ".mts", ".cts")
PRISMA_CONFIG_BASENAMES = (
    "prisma7.config",
    "prisma.config",
    ".config/prisma7",
    ".config/prisma",
    ".config/prisma7.config",
    ".config/prisma.config",
)


def _build_forbidden_config_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    for prefix in ("", "server/"):
        for basename in PRISMA_CONFIG_BASENAMES:
            for ext in PRISMA_CONFIG_EXTENSIONS:
                direct = f"{prefix}{basename}{ext}"
                if direct != CANONICAL_CONFIG_REL_PATH:
                    candidates.append(direct)
                candidates.append(f"{prefix}{basename}/index{ext}")
    return tuple(dict.fromkeys(candidates))


def _build_forbidden_config_dirs() -> tuple[str, ...]:
    dirs: list[str] = []
    for prefix in ("", "server/"):
        for basename in PRISMA_CONFIG_BASENAMES:
            dirs.append(f"{prefix}{basename}")
    return tuple(dict.fromkeys(dirs))


FORBIDDEN_CONFIG_CANDIDATES = _build_forbidden_config_candidates()
FORBIDDEN_CONFIG_DIR_OR_LINK_BASENAMES = _build_forbidden_config_dirs()
FORBIDDEN_HIDDEN_CONFIG_ROOTS = (".config", "server/.config")
FORBIDDEN_ALTERNATE_SCHEMA_PATHS = (
    "schema.prisma",
    "prisma/schema.prisma",
    "server/schema.prisma",
)
DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)

FORBIDDEN_SHELL_RE = re.compile(r"[;|&><`$(){}\\\n\r\0]")
ENV_ASSIGN_LIKE_RE = re.compile(r"^([^=\s]+)=(.*)$")
SAFE_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ZERO_SHA_RE = re.compile(r"^0+$")
SAFE_DB_TEST_PATH_RE = re.compile(
    r"^(?:\./)?src/__tests__/database(?:/|/(?:\*|[A-Za-z0-9_.-]+)\.test\.ts)?$"
)
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
SQL_LINE_COMMENT_RE = re.compile(r"--[^\r\n]*")
JS_LINE_COMMENT_RE = re.compile(r"//[^\r\n]*")
RUNNABLE_TEST_RE = re.compile(r"(?<![.\w])(?:test|it)\s*\(")
LOCK_PROVIDER_RE = re.compile(r"""^\s*provider\s*=\s*(["'])([^"']+)\1\s*$""")
LOCKFILE_PRISMA_PATH_RE = re.compile(r"^(?:.+/)?node_modules/(prisma|@prisma/client)$")


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


def load_json_object(abs_path: str, display_path: str) -> tuple[dict[str, object] | None, str | None]:
    try:
        with open(abs_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{display_path} could not be read as valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"{display_path} must contain a JSON object at top level"
    return data, None


def validate_regular_non_symlink_path(repo_root: str, rel_path: str) -> str | None:
    """Ensure rel_path and all intermediate directories under repo_root contain no symlinks and stay inside repo_root."""
    norm_rel = rel_path.replace("\\", "/").strip("/")
    parts = [p for p in norm_rel.split("/") if p]
    if not parts or ".." in parts or "." in parts:
        return f"Invalid relative path: {rel_path}"

    real_root = os.path.realpath(repo_root)
    cur = repo_root
    for idx, part in enumerate(parts):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            partial = "/".join(parts[: idx + 1])
            return f"Symlink path is not permitted for '{partial}' (canonical non-symlink path required)"

    target = os.path.join(repo_root, *parts)
    if not os.path.lexists(target):
        return f"Required path does not exist: {norm_rel}"
    real_target = os.path.realpath(target)
    expected_real = os.path.join(real_root, *parts)
    if real_target != expected_real:
        return f"Path '{norm_rel}' resolves outside its canonical workspace location"
    return None


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
            ["ls-tree", "-r", "--full-tree", base_ref, "--", CANONICAL_MIGRATIONS_REL_DIR],
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
        link_err = validate_regular_non_symlink_path(repo_root, rel_path)
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.lexists(abs_path) or os.path.islink(abs_path) or not os.path.isfile(abs_path):
            errors.append(
                f"Existing migration from base branch cannot be deleted, symlinked, or renamed: {rel_path}"
            )
            continue
        if link_err:
            errors.append(link_err)
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
    dir_link_err = validate_regular_non_symlink_path(repo_root, CANONICAL_MIGRATIONS_REL_DIR)
    migrations_dir = os.path.join(repo_root, CANONICAL_MIGRATIONS_REL_DIR)
    if not os.path.isdir(migrations_dir) or os.path.islink(migrations_dir):
        errors.append("server/prisma/migrations/ must exist as a non-symlink directory")
        return errors, 0
    if dir_link_err:
        errors.append(dir_link_err)

    lock_rel = f"{CANONICAL_MIGRATIONS_REL_DIR}/migration_lock.toml"
    lock_err = validate_regular_non_symlink_path(repo_root, lock_rel)
    lock_path = os.path.join(migrations_dir, "migration_lock.toml")
    if lock_err and os.path.lexists(lock_path):
        errors.append(lock_err)
    elif not os.path.isfile(lock_path) or os.path.getsize(lock_path) == 0:
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
    for root_dir, dirs, files in os.walk(migrations_dir, followlinks=False):
        for dname in dirs:
            dpath = os.path.join(root_dir, dname)
            if os.path.islink(dpath):
                rel = os.path.relpath(dpath, repo_root).replace(os.sep, "/")
                errors.append(f"Symlink directory is not permitted inside migrations: {rel}")
        for fname in files:
            if fname != "migration.sql":
                continue
            abs_file = os.path.join(root_dir, fname)
            rel_to_migrations = os.path.relpath(abs_file, migrations_dir)
            parts = rel_to_migrations.split(os.sep)
            repo_rel = os.path.join(CANONICAL_MIGRATIONS_REL_DIR, rel_to_migrations).replace(os.sep, "/")
            if len(parts) != 2 or not parts[0].strip() or parts[0].startswith("."):
                errors.append(
                    f"Migration file must reside directly inside a valid migration subdirectory: {repo_rel}"
                )
                continue
            mig_link_err = validate_regular_non_symlink_path(repo_root, repo_rel)
            if mig_link_err:
                errors.append(mig_link_err)
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
    if not os.path.isdir(test_dir) or os.path.islink(test_dir):
        errors.append("server/src/__tests__/database/ directory must exist when schema.prisma is present")
        return errors, 0

    test_files = sorted(glob.glob(os.path.join(test_dir, "*.test.ts")))
    if not test_files:
        errors.append("server/src/__tests__/database/ must contain at least one *.test.ts file")
        return errors, 0

    runnable_files = 0
    for abs_path in test_files:
        rel_path = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
        link_err = validate_regular_non_symlink_path(repo_root, rel_path)
        if link_err:
            errors.append(link_err)
            continue
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


def _tokenize_canonical_ts_config(source: str) -> tuple[list[tuple[str, str]], str | None]:
    """Strictly tokenize server/prisma7.config.ts without comments, escapes, or dynamic JS/TS syntax."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(source)
    punct = set("{}()[]:,;.")

    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if source.startswith("//", i) or source.startswith("/*", i):
            return [], "server/prisma7.config.ts cannot contain comments outside the canonical template"
        if ch == "`":
            return [], "server/prisma7.config.ts cannot contain template literals"
        if ch in ('"', "'"):
            quote = ch
            j = i + 1
            chars: list[str] = []
            while j < n and source[j] != quote:
                c = source[j]
                if c in "\r\n":
                    return [], "server/prisma7.config.ts contains an unterminated string literal"
                if c == "\\":
                    return [], "server/prisma7.config.ts cannot use backslash escape sequences in string literals"
                chars.append(c)
                j += 1
            if j >= n:
                return [], "server/prisma7.config.ts contains an unterminated string literal"
            tokens.append(("STRING", "".join(chars)))
            i = j + 1
            continue
        if ch in punct:
            tokens.append(("PUNCT", ch))
            i += 1
            continue
        if ch.isalpha() or ch in "_$":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] in "_$"):
                j += 1
            tokens.append(("IDENT", source[i:j]))
            i = j
            continue
        return [], f"server/prisma7.config.ts contains disallowed syntax character {ch!r}"

    return tokens, None


class _CanonicalConfigParser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> tuple[str, str] | None:
        idx = self.pos + offset
        if 0 <= idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def consume(self, kind: str | None = None, value: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ValueError(f"Unexpected end of file; expected {value or kind}")
        if kind is not None and tok[0] != kind:
            raise ValueError(f"Unexpected token {tok[1]!r}; expected {value or kind}")
        if value is not None and tok[1] != value:
            raise ValueError(f"Unexpected token {tok[1]!r}; expected {value!r}")
        self.pos += 1
        return tok

    def optional_punct(self, value: str) -> bool:
        tok = self.peek()
        if tok == ("PUNCT", value):
            self.pos += 1
            return True
        return False

    def parse(self) -> None:
        # Statement 1: import "dotenv/config";
        self.consume("IDENT", "import")
        _, dotenv_spec = self.consume("STRING")
        if dotenv_spec != "dotenv/config":
            raise ValueError(f"First import must be 'dotenv/config' (got: {dotenv_spec!r})")
        self.optional_punct(";")

        # Statement 2: import { defineConfig } from "prisma/config";
        self.consume("IDENT", "import")
        self.consume("PUNCT", "{")
        _, fn_name = self.consume("IDENT")
        if fn_name != "defineConfig":
            raise ValueError(f"Must import 'defineConfig' from 'prisma/config' (got: {fn_name!r})")
        self.optional_punct(",")
        self.consume("PUNCT", "}")
        self.consume("IDENT", "from")
        _, cfg_pkg = self.consume("STRING")
        if cfg_pkg != "prisma/config":
            raise ValueError(f"Second import must come strictly from 'prisma/config' (got: {cfg_pkg!r})")
        self.optional_punct(";")

        # Statement 3: export default defineConfig({ ... });
        self.consume("IDENT", "export")
        self.consume("IDENT", "default")
        self.consume("IDENT", "defineConfig")
        self.consume("PUNCT", "(")
        self._parse_root_object()
        self.consume("PUNCT", ")")
        self.optional_punct(";")

        if self.peek() is not None:
            extra = self.peek()
            raise ValueError(f"Unexpected extra statement or token {extra[1]!r} after defineConfig(...)")

    def _parse_root_object(self) -> None:
        self.consume("PUNCT", "{")
        seen_keys: set[str] = set()
        expected_keys = {"schema", "migrations", "datasource"}

        while self.peek() != ("PUNCT", "}"):
            _, key = self.consume("IDENT")
            if key not in expected_keys:
                raise ValueError(f"Unsupported top-level key {key!r} in defineConfig object")
            if key in seen_keys:
                raise ValueError(f"Duplicate key {key!r} in defineConfig object")
            seen_keys.add(key)
            self.consume("PUNCT", ":")

            if key == "schema":
                _, schema_val = self.consume("STRING")
                if schema_val != "prisma/schema.prisma":
                    raise ValueError(
                        f"Canonical schema must equal 'prisma/schema.prisma' (got: {schema_val!r})"
                    )
            elif key == "migrations":
                self._parse_migrations_object()
            elif key == "datasource":
                self._parse_datasource_object()

            if self.peek() == ("PUNCT", ","):
                self.consume("PUNCT", ",")
            elif self.peek() != ("PUNCT", "}"):
                tok = self.peek()
                raise ValueError(f"Expected ',' or '}}' in defineConfig object, got {tok[1]!r}")

        self.consume("PUNCT", "}")
        missing = sorted(expected_keys - seen_keys)
        if missing:
            raise ValueError(f"Missing required key(s) in defineConfig object: {missing}")

    def _parse_migrations_object(self) -> None:
        self.consume("PUNCT", "{")
        self.consume("IDENT", "path")
        self.consume("PUNCT", ":")
        _, mig_path = self.consume("STRING")
        if mig_path != "prisma/migrations":
            raise ValueError(
                f"Canonical migrations.path must equal 'prisma/migrations' (got: {mig_path!r})"
            )
        self.optional_punct(",")
        if self.peek() != ("PUNCT", "}"):
            raise ValueError("migrations block may only contain the 'path' property")
        self.consume("PUNCT", "}")

    def _parse_datasource_object(self) -> None:
        self.consume("PUNCT", "{")
        self.consume("IDENT", "url")
        self.consume("PUNCT", ":")
        # Strict: process.env["DATABASE_URL"]
        self.consume("IDENT", "process")
        self.consume("PUNCT", ".")
        self.consume("IDENT", "env")
        self.consume("PUNCT", "[")
        _, env_name = self.consume("STRING")
        if env_name != "DATABASE_URL":
            raise ValueError(
                f"datasource.url must strictly read process.env['DATABASE_URL'] (got: {env_name!r})"
            )
        self.consume("PUNCT", "]")
        self.optional_punct(",")
        if self.peek() != ("PUNCT", "}"):
            raise ValueError("datasource block may only contain url: process.env['DATABASE_URL']")
        self.consume("PUNCT", "}")


def validate_canonical_prisma_config_content(content: str) -> list[str]:
    """Validate that server/prisma7.config.ts matches the deterministic canonical AST template."""
    if not content.strip():
        return ["server/prisma7.config.ts cannot be empty"]
    tokens, tok_err = _tokenize_canonical_ts_config(content)
    if tok_err:
        return [tok_err]
    try:
        _CanonicalConfigParser(tokens).parse()
    except ValueError as exc:
        return [f"server/prisma7.config.ts violates canonical configuration contract: {exc}"]
    return []


def validate_prisma_config(repo_root: str, *, require_canonical: bool) -> list[str]:
    """Allow strictly canonical server/prisma7.config.ts (when required) and reject all alternate config/schema paths."""
    errors: list[str] = []

    for rel_path in FORBIDDEN_CONFIG_CANDIDATES:
        candidate = os.path.join(repo_root, rel_path)
        if os.path.lexists(candidate):
            errors.append(
                f"Alternate Prisma config file '{rel_path}' is not permitted; only '{CANONICAL_CONFIG_REL_PATH}' is allowed"
            )

    for rel_dir in FORBIDDEN_CONFIG_DIR_OR_LINK_BASENAMES:
        candidate = os.path.join(repo_root, rel_dir)
        if os.path.islink(candidate):
            errors.append(
                f"Symlink Prisma config path '{rel_dir}' is not permitted; only '{CANONICAL_CONFIG_REL_PATH}' is allowed"
            )
        elif os.path.isdir(candidate):
            entries = os.listdir(candidate)
            if entries:
                errors.append(
                    f"Alternate Prisma config directory '{rel_dir}/' is not permitted; only '{CANONICAL_CONFIG_REL_PATH}' is allowed"
                )

    for hidden_root in FORBIDDEN_HIDDEN_CONFIG_ROOTS:
        candidate = os.path.join(repo_root, hidden_root)
        if os.path.islink(candidate):
            errors.append(
                f"Symlink configuration directory '{hidden_root}' is not permitted"
            )

    for rel_schema in FORBIDDEN_ALTERNATE_SCHEMA_PATHS:
        if os.path.lexists(os.path.join(repo_root, rel_schema)):
            errors.append(
                f"Alternate Prisma schema path '{rel_schema}' is not permitted; schema must live at '{CANONICAL_SCHEMA_REL_PATH}'"
            )

    root_pkg_path = os.path.join(repo_root, "package.json")
    if os.path.lexists(root_pkg_path):
        root_pkg, root_err = load_json_object(root_pkg_path, "package.json")
        if root_err:
            errors.append(root_err)
        elif root_pkg is not None and "prisma" in root_pkg:
            errors.append(
                "Root package.json cannot define a 'prisma' configuration block; only server/prisma7.config.ts is permitted"
            )

    server_pkg_path = os.path.join(repo_root, "server/package.json")
    if os.path.lexists(server_pkg_path):
        server_pkg, srv_err = load_json_object(server_pkg_path, "server/package.json")
        if srv_err:
            errors.append(srv_err)
        elif server_pkg is not None and "prisma" in server_pkg:
            errors.append(
                "server/package.json cannot define a legacy 'prisma' configuration block; use canonical server/prisma7.config.ts only"
            )

    if require_canonical:
        cfg_link_err = validate_regular_non_symlink_path(repo_root, CANONICAL_CONFIG_REL_PATH)
        cfg_abs = os.path.join(repo_root, CANONICAL_CONFIG_REL_PATH)
        if not os.path.lexists(cfg_abs):
            errors.append(
                f"{CANONICAL_CONFIG_REL_PATH} must exist alongside {CANONICAL_SCHEMA_REL_PATH}"
            )
        elif cfg_link_err:
            errors.append(cfg_link_err)
        elif not os.path.isfile(cfg_abs):
            errors.append(f"{CANONICAL_CONFIG_REL_PATH} must be a regular file")
        else:
            try:
                with open(cfg_abs, encoding="utf-8") as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"Failed to read {CANONICAL_CONFIG_REL_PATH}: {exc}")
            else:
                errors.extend(validate_canonical_prisma_config_content(content))

    return errors


def validate_prisma_versions(repo_root: str) -> list[str]:
    """Validate exact Prisma 7.10.1 versions in package.json files and root package-lock.json."""
    errors: list[str] = []

    root_pkg_path = os.path.join(repo_root, "package.json")
    if os.path.lexists(root_pkg_path):
        root_pkg, root_err = load_json_object(root_pkg_path, "package.json")
        if root_err:
            errors.append(root_err)
        elif root_pkg is not None:
            for section in (*DEPENDENCY_SECTIONS, "overrides"):
                block = root_pkg.get(section)
                if isinstance(block, dict):
                    for pkg_name in ("prisma", "@prisma/client"):
                        if pkg_name in block:
                            errors.append(
                                f"Root package.json {section} cannot declare '{pkg_name}'; pin {CANONICAL_PRISMA_VERSION} strictly inside server/package.json"
                            )

    server_pkg_path = os.path.join(repo_root, "server/package.json")
    if not os.path.lexists(server_pkg_path):
        errors.append("server/package.json must exist when Prisma artifacts are present")
        return errors

    server_pkg, srv_err = load_json_object(server_pkg_path, "server/package.json")
    if srv_err or server_pkg is None:
        errors.append(srv_err or "server/package.json must be a JSON object")
        return errors

    dev_deps = server_pkg.get("devDependencies")
    deps = server_pkg.get("dependencies")
    prisma_ver = dev_deps.get("prisma") if isinstance(dev_deps, dict) else None
    client_ver = deps.get("@prisma/client") if isinstance(deps, dict) else None

    if prisma_ver != CANONICAL_PRISMA_VERSION:
        errors.append(
            f"server/package.json devDependencies.prisma must be pinned strictly to '{CANONICAL_PRISMA_VERSION}' (found: {prisma_ver!r})"
        )
    if client_ver != CANONICAL_PRISMA_VERSION:
        errors.append(
            f"server/package.json dependencies['@prisma/client'] must be pinned strictly to '{CANONICAL_PRISMA_VERSION}' (found: {client_ver!r})"
        )

    for bad_section, forbidden_pkg in (
        ("dependencies", "prisma"),
        ("optionalDependencies", "prisma"),
        ("peerDependencies", "prisma"),
        ("devDependencies", "@prisma/client"),
        ("optionalDependencies", "@prisma/client"),
        ("peerDependencies", "@prisma/client"),
    ):
        block = server_pkg.get(bad_section)
        if isinstance(block, dict) and forbidden_pkg in block:
            errors.append(
                f"server/package.json {bad_section} cannot contain '{forbidden_pkg}'; place 'prisma' in devDependencies and '@prisma/client' in dependencies"
            )

    if os.path.lexists(os.path.join(repo_root, "server/package-lock.json")):
        errors.append(
            "server/package-lock.json is not permitted; dependencies must be locked in root package-lock.json"
        )

    lock_path = os.path.join(repo_root, "package-lock.json")
    if not os.path.lexists(lock_path):
        errors.append("Root package-lock.json must exist and lock Prisma packages to 7.10.1")
        return errors

    lock_data, lock_err = load_json_object(lock_path, "package-lock.json")
    if lock_err or lock_data is None:
        errors.append(lock_err or "package-lock.json must contain a valid JSON object")
        return errors

    packages = lock_data.get("packages")
    if not isinstance(packages, dict):
        errors.append("package-lock.json must contain a valid 'packages' map")
        return errors

    server_ws = packages.get("server")
    if isinstance(server_ws, dict):
        ws_dev = server_ws.get("devDependencies")
        ws_deps = server_ws.get("dependencies")
        if isinstance(ws_dev, dict) and ws_dev.get("prisma") != CANONICAL_PRISMA_VERSION:
            errors.append(
                f"package-lock.json packages.server.devDependencies.prisma must equal '{CANONICAL_PRISMA_VERSION}' (got: {ws_dev.get('prisma')!r})"
            )
        if isinstance(ws_deps, dict) and ws_deps.get("@prisma/client") != CANONICAL_PRISMA_VERSION:
            errors.append(
                f"package-lock.json packages.server.dependencies['@prisma/client'] must equal '{CANONICAL_PRISMA_VERSION}' (got: {ws_deps.get('@prisma/client')!r})"
            )

    for pkg_name in ("prisma", "@prisma/client"):
        nested_key = f"server/node_modules/{pkg_name}"
        hoisted_key = f"node_modules/{pkg_name}"
        resolved_entry = packages.get(nested_key)
        resolved_key = nested_key
        if not isinstance(resolved_entry, dict):
            resolved_entry = packages.get(hoisted_key)
            resolved_key = hoisted_key
        if not isinstance(resolved_entry, dict):
            errors.append(
                f"package-lock.json is missing resolved lockfile entry for workspace package '{pkg_name}'"
            )
        else:
            locked_ver = resolved_entry.get("version")
            if locked_ver != CANONICAL_PRISMA_VERSION:
                errors.append(
                    f"package-lock.json entry '{resolved_key}' must lock version '{CANONICAL_PRISMA_VERSION}' (got: {locked_ver!r})"
                )

    for pkg_key, entry in sorted(packages.items()):
        if not isinstance(pkg_key, str) or not isinstance(entry, dict):
            continue
        match = LOCKFILE_PRISMA_PATH_RE.match(pkg_key)
        if not match:
            continue
        locked_ver = entry.get("version")
        if locked_ver != CANONICAL_PRISMA_VERSION:
            errors.append(
                f"package-lock.json entry '{pkg_key}' resolves '{match.group(1)}' to {locked_ver!r} instead of '{CANONICAL_PRISMA_VERSION}'"
            )

    return errors


def detect_partial_sbs19_artifacts(repo_root: str) -> list[str]:
    """Detect partial SBS-19 artifacts when server/prisma/schema.prisma is absent so baseline never returns false N/A."""
    signals: list[str] = []

    for rel_path in (
        CANONICAL_CONFIG_REL_PATH,
        "server/prisma",
        CANONICAL_MIGRATIONS_REL_DIR,
        CANONICAL_SEED_REL_PATH,
        "server/src/__tests__/database",
    ):
        if os.path.lexists(os.path.join(repo_root, rel_path)):
            signals.append(
                f"Partial SBS-19 artifact '{rel_path}' exists without '{CANONICAL_SCHEMA_REL_PATH}'"
            )

    for pkg_rel in ("package.json", "server/package.json"):
        abs_pkg = os.path.join(repo_root, pkg_rel)
        if not os.path.lexists(abs_pkg):
            continue
        pkg_data, pkg_err = load_json_object(abs_pkg, pkg_rel)
        if pkg_err or pkg_data is None:
            signals.append(pkg_err or f"Invalid JSON in {pkg_rel}")
            continue
        for section in (*DEPENDENCY_SECTIONS, "overrides"):
            block = pkg_data.get(section)
            if isinstance(block, dict):
                for pkg_name in ("prisma", "@prisma/client"):
                    if pkg_name in block:
                        signals.append(
                            f"Partial SBS-19 dependency '{pkg_name}' declared in {pkg_rel} {section} without '{CANONICAL_SCHEMA_REL_PATH}'"
                        )
        if pkg_rel == "server/package.json":
            scripts = pkg_data.get("scripts")
            if isinstance(scripts, dict):
                for script_name in SCRIPT_VALIDATORS:
                    if script_name in scripts:
                        signals.append(
                            f"Partial SBS-19 script 'scripts.{script_name}' declared in server/package.json without '{CANONICAL_SCHEMA_REL_PATH}'"
                        )

    lock_path = os.path.join(repo_root, "package-lock.json")
    if os.path.lexists(lock_path):
        lock_data, lock_err = load_json_object(lock_path, "package-lock.json")
        if lock_err or lock_data is None:
            signals.append(lock_err or "Invalid JSON in package-lock.json")
        else:
            packages = lock_data.get("packages")
            if isinstance(packages, dict):
                for pkg_key in sorted(packages.keys()):
                    if isinstance(pkg_key, str) and LOCKFILE_PRISMA_PATH_RE.match(pkg_key):
                        signals.append(
                            f"Partial SBS-19 lockfile entry '{pkg_key}' exists in package-lock.json without '{CANONICAL_SCHEMA_REL_PATH}'"
                        )

    return signals


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


def consume_canonical_prisma_schema_flag(
    args: list[str], *, require_schema: bool = False
) -> tuple[list[str], bool, str | None]:
    """Validate explicit canonical --schema=prisma/schema.prisma flag; reject alternates, duplicates, and --config."""
    out: list[str] = []
    seen_schema = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--config" or arg.startswith("--config="):
            return [], False, "--config option is not permitted because canonical server/prisma7.config.ts must be used"
        if arg.startswith("--schema="):
            if seen_schema:
                return [], False, "Duplicate --schema flag is not allowed"
            val = arg.split("=", 1)[1]
            if val not in CANONICAL_SCHEMA_PATHS:
                return (
                    [],
                    False,
                    f"Non-canonical --schema path is rejected (expected 'prisma/schema.prisma', got: {val!r})",
                )
            seen_schema = True
            i += 1
        elif arg == "--schema":
            if seen_schema:
                return [], False, "Duplicate --schema flag is not allowed"
            if i + 1 >= len(args):
                return [], False, "Empty or missing value for --schema option"
            val = args[i + 1]
            if val not in CANONICAL_SCHEMA_PATHS:
                return (
                    [],
                    False,
                    f"Non-canonical --schema path is rejected (expected 'prisma/schema.prisma', got: {val!r})",
                )
            seen_schema = True
            i += 2
        else:
            out.append(arg)
            i += 1

    if require_schema and not seen_schema:
        return [], False, "Missing required explicit canonical '--schema=prisma/schema.prisma' option"
    return out, seen_schema, None


def validate_db_validate_script(exe: str, args: list[str]) -> str | None:
    if exe != "prisma":
        return "server/package.json scripts.db:validate must directly invoke exact executable 'prisma validate --schema=prisma/schema.prisma'"
    core_args, seen_schema, err = consume_canonical_prisma_schema_flag(args, require_schema=True)
    if err or not seen_schema:
        return f"server/package.json scripts.db:validate: {err or 'missing explicit --schema=prisma/schema.prisma'}"
    if core_args != ["validate"]:
        return "server/package.json scripts.db:validate must strictly run 'prisma validate --schema=prisma/schema.prisma' without extra commands or flags"
    return None


def validate_db_migrate_deploy_script(exe: str, args: list[str]) -> str | None:
    if exe != "prisma":
        return "server/package.json scripts.db:migrate:deploy must directly invoke exact executable 'prisma migrate deploy --schema=prisma/schema.prisma'"
    core_args, seen_schema, err = consume_canonical_prisma_schema_flag(args, require_schema=True)
    if err or not seen_schema:
        return f"server/package.json scripts.db:migrate:deploy: {err or 'missing explicit --schema=prisma/schema.prisma'}"
    if core_args != ["migrate", "deploy"]:
        return "server/package.json scripts.db:migrate:deploy must strictly run 'prisma migrate deploy --schema=prisma/schema.prisma' without extra commands or flags"
    return None


def validate_db_seed_script(exe: str, args: list[str]) -> str | None:
    if exe == "tsx" and args == ["prisma/seed.ts"]:
        return None
    return "server/package.json scripts.db:seed must strictly invoke 'tsx prisma/seed.ts'"


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


def validate_scripts(repo_root: str) -> list[str]:
    errors: list[str] = []
    pkg_path = os.path.join(repo_root, "server/package.json")
    if not os.path.isfile(pkg_path):
        return ["server/package.json must exist"]

    pkg_data, pkg_err = load_json_object(pkg_path, "server/package.json")
    if pkg_err or pkg_data is None:
        return [pkg_err or "server/package.json must contain a valid JSON object"]

    scripts = pkg_data.get("scripts")
    if not isinstance(scripts, dict):
        return ["server/package.json scripts block must be an object"]

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
        base_has_schema = git_object_exists(repo_root, f"{base_ref}:{CANONICAL_SCHEMA_REL_PATH}")
    except GitInspectionError as exc:
        print(f"::error::{exc}")
        write_github_output(args.github_output, "run_prisma", "false")
        return 1

    schema_path = os.path.join(repo_root, CANONICAL_SCHEMA_REL_PATH)
    pr_has_schema = os.path.lexists(schema_path)

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
        baseline_errors: list[str] = []
        baseline_errors.extend(immutability_errors)
        baseline_errors.extend(validate_prisma_config(repo_root, require_canonical=False))
        baseline_errors.extend(detect_partial_sbs19_artifacts(repo_root))
        if baseline_errors:
            for err in baseline_errors:
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

    schema_link_err = validate_regular_non_symlink_path(repo_root, CANONICAL_SCHEMA_REL_PATH)
    if schema_link_err:
        errors.append(schema_link_err)
    elif not os.path.isfile(schema_path):
        errors.append("server/prisma/schema.prisma must be a regular file")
    else:
        with open(schema_path, encoding="utf-8") as fh:
            if not fh.read().strip():
                errors.append("server/prisma/schema.prisma must be non-empty")

    errors.extend(validate_prisma_config(repo_root, require_canonical=True))
    errors.extend(validate_prisma_versions(repo_root))

    mig_errors, mig_count = validate_migrations(repo_root)
    errors.extend(mig_errors)

    seed_path = os.path.join(repo_root, CANONICAL_SEED_REL_PATH)
    seed_link_err = validate_regular_non_symlink_path(repo_root, CANONICAL_SEED_REL_PATH)
    if not os.path.lexists(seed_path):
        errors.append("server/prisma/seed.ts must exist")
    elif seed_link_err:
        errors.append(seed_link_err)
    elif not os.path.isfile(seed_path):
        errors.append("server/prisma/seed.ts must be a regular file")
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
        f"Verified SBS-19 database contract: Prisma {CANONICAL_PRISMA_VERSION}, {CANONICAL_CONFIG_REL_PATH}, "
        f"{mig_count} valid migration(s), {test_file_count} runnable database test file(s), canonical paths and immutability intact."
    )
    write_github_output(args.github_output, "run_prisma", "true")
    return 0


def cmd_verify_runtime_versions(args: argparse.Namespace) -> int:
    """Verify installed node_modules Prisma CLI and @prisma/client match exact 7.10.1."""
    repo_root = os.path.abspath(args.repo_root)
    errors: list[str] = []

    for pkg_name in ("prisma", "@prisma/client"):
        nested_pkg = os.path.join(repo_root, "server/node_modules", pkg_name, "package.json")
        hoisted_pkg = os.path.join(repo_root, "node_modules", pkg_name, "package.json")
        target = nested_pkg if os.path.isfile(nested_pkg) else hoisted_pkg
        rel_display = os.path.relpath(target, repo_root).replace(os.sep, "/")

        if not os.path.isfile(target):
            errors.append(
                f"Installed package '{pkg_name}' was not found in server/node_modules or node_modules"
            )
            continue

        data, err = load_json_object(target, rel_display)
        if err or data is None:
            errors.append(err or f"Invalid package metadata in {rel_display}")
            continue
        actual_ver = data.get("version")
        if actual_ver != CANONICAL_PRISMA_VERSION:
            errors.append(
                f"Installed runtime '{pkg_name}' at {rel_display} has version {actual_ver!r}; expected {CANONICAL_PRISMA_VERSION!r}"
            )

    if errors:
        for err in errors:
            print(f"::error::{err}")
        return 1

    print(f"Verified installed Prisma CLI and @prisma/client runtime versions match {CANONICAL_PRISMA_VERSION}.")
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
        contract_note = "Canonical Prisma 7.10.1 config, version, migration, and script contract validated"
    elif contract_outcome == "failure":
        contract_status = "FAIL"
        contract_note = "Schema, canonical config, version pin, migration immutability, base ref, or script contract check failed"
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

    ver_p = subparsers.add_parser("verify-runtime-versions")
    ver_p.add_argument("--repo-root", default=".")
    ver_p.set_defaults(func=cmd_verify_runtime_versions)

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
