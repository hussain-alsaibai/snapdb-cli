"""Tests for snapdb-cli.

Every test drives the real CLI entry point as a subprocess, because the
defects this suite was written to catch were all in the argument plumbing and
the SnapDB API usage, not in a pure function.

History: before 2026-11-09 this package had no tests and no CI. Its README
documented `snapdb-cli init users id:i32,name:str,email:str`, which failed on
the first command a new user ran, twice over: `str` is not a SnapDB dtype
(text is fixed-width `bytes:N`), and `SnapDB.create()` / `SnapDB.open()` do
not exist in the library's API. Every documented command after that failed
because the database was never created.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CLI = HERE / "snapdb_cli.py"


def run(*args, cwd=None):
    """Run the CLI and return (returncode, stdout, stderr)."""
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


@pytest.fixture()
def workdir(tmp_path):
    return tmp_path


def init_users(workdir, name="users", schema="id:i32,name:bytes:16,email:bytes:32"):
    rc = run("init", name, schema, "--path", str(workdir))
    assert rc.returncode == 0, rc.stderr
    return name


# ---- the documented walkthrough must actually run -------------------------


def test_documented_schema_creates_a_database(workdir):
    """The README schema must be a schema SnapDB accepts."""
    init_users(workdir)
    assert (workdir / "users.snap").exists()


def test_insert_then_get_round_trips(workdir):
    init_users(workdir)
    rc = run(
        "insert",
        "users",
        '{"id": 1, "name": "alice", "email": "alice@example.com"}',
        "--path",
        str(workdir),
    )
    assert rc.returncode == 0, rc.stderr
    rc = run("get", "users", "0", "--path", str(workdir))
    assert rc.returncode == 0, rc.stderr
    assert json.loads(rc.stdout) == {
        "id": 1,
        "name": "alice",
        "email": "alice@example.com",
    }


def test_list_and_count_agree(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    run("insert", "users", '{"id": 2, "name": "bob", "email": "b@x.io"}', "--path", str(workdir))
    listed = run("list", "users", "--path", str(workdir)).stdout
    counted = run("count", "users", "--path", str(workdir)).stdout
    assert "Total rows: 2" in listed
    assert listed.count("[") == 2
    assert "Row count: 2" in counted


def test_export_json_is_valid_json_of_every_row(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    run("insert", "users", '{"id": 2, "name": "bob", "email": "b@x.io"}', "--path", str(workdir))
    out = run("export", "users", "--format", "json", "--path", str(workdir)).stdout
    rows = json.loads(out)
    assert [r["name"] for r in rows] == ["alice", "bob"]


def test_export_csv_has_header_and_rows(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    out = run("export", "users", "--format", "csv", "--path", str(workdir)).stdout
    lines = out.strip().splitlines()
    assert lines[0] == "id,name,email"
    assert lines[1] == "1,alice,a@x.io"


def test_export_csv_of_empty_table_still_emits_header(workdir):
    """A headerless CSV reads downstream as a file with no columns."""
    init_users(workdir)
    out = run("export", "users", "--format", "csv", "--path", str(workdir)).stdout
    assert out.strip() == "id,name,email"


def test_export_ndjson_is_one_object_per_line(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    run("insert", "users", '{"id": 2, "name": "bob", "email": "b@x.io"}', "--path", str(workdir))
    lines = run("export", "users", "--format", "ndjson", "--path", str(workdir)).stdout.strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["id"] for line in lines] == [1, 2]


def test_schema_reports_the_declared_types(workdir):
    init_users(workdir)
    out = run("schema", "users", "--path", str(workdir)).stdout
    assert "id: i32" in out
    assert "name: bytes:16" in out
    # The printed spec must be pasteable back into init.
    assert "id:i32,name:bytes:16,email:bytes:32" in out


def test_stats_reports_row_count_and_size(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    out = run("stats", "users", "--path", str(workdir)).stdout
    assert "Rows:     1" in out
    assert "bytes" in out


def test_delete_removes_the_row(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    run("insert", "users", '{"id": 2, "name": "bob", "email": "b@x.io"}', "--path", str(workdir))
    assert run("delete", "users", "1", "--path", str(workdir)).returncode == 0
    assert "Row count: 1" in run("count", "users", "--path", str(workdir)).stdout


def test_delete_of_a_missing_row_errors_and_leaves_data_alone(workdir):
    init_users(workdir)
    run("insert", "users", '{"id": 1, "name": "alice", "email": "a@x.io"}', "--path", str(workdir))
    rc = run("delete", "users", "99", "--path", str(workdir))
    assert rc.returncode != 0
    assert "does not exist" in rc.stderr
    assert "Row count: 1" in run("count", "users", "--path", str(workdir)).stdout


def test_benchmark_runs(workdir):
    """A benchmark that cannot open its own scratch db measures nothing."""
    init_users(workdir)
    rc = run("benchmark", "users", "--ops", "50", "--path", str(workdir))
    assert rc.returncode == 0, rc.stderr
    assert "ops/sec" in rc.stdout


def test_bulk_insert_accepts_a_json_array(workdir):
    init_users(workdir)
    rc = run(
        "insert",
        "users",
        '[{"id":1,"name":"a","email":"a@x.io"},{"id":2,"name":"b","email":"b@x.io"}]',
        "--path",
        str(workdir),
    )
    assert rc.returncode == 0, rc.stderr
    assert "Row count: 2" in run("count", "users", "--path", str(workdir)).stdout


# ---- the schema parser must explain the mistake, not traceback ------------


@pytest.mark.parametrize("bad", ["str", "string", "text", "varchar"])
def test_text_dtypes_are_rejected_with_the_fix(workdir, bad):
    rc = run("init", "bad", "id:i32,name:" + bad, "--path", str(workdir))
    assert rc.returncode != 0
    assert "not a SnapDB dtype" in rc.stderr
    assert "bytes:32" in rc.stderr, "the error must show the working alternative"
    assert "Traceback" not in rc.stderr
    assert not (workdir / "bad.snap").exists()


def test_bare_bytes_is_rejected_with_a_width_example(workdir):
    rc = run("init", "bad", "id:i32,name:bytes", "--path", str(workdir))
    assert rc.returncode != 0
    assert "needs a width" in rc.stderr
    assert "bytes:32" in rc.stderr


def test_unknown_dtype_lists_the_valid_ones(workdir):
    rc = run("init", "bad", "id:int32", "--path", str(workdir))
    assert rc.returncode != 0
    assert "unknown dtype" in rc.stderr
    assert "i32" in rc.stderr


def test_duplicate_init_refuses_to_clobber(workdir):
    init_users(workdir)
    rc = run("init", "users", "id:i32", "--path", str(workdir))
    assert rc.returncode != 0
    assert "already exists" in rc.stderr
    # The original schema must survive the refusal.
    assert "name: bytes:16" in run("schema", "users", "--path", str(workdir)).stdout


def test_missing_database_names_the_expected_path(workdir):
    rc = run("count", "nope", "--path", str(workdir))
    assert rc.returncode != 0
    assert "not found" in rc.stderr
    assert "nope.snap" in rc.stderr


def test_invalid_json_is_reported_not_raised(workdir):
    init_users(workdir)
    rc = run("insert", "users", "{not json", "--path", str(workdir))
    assert rc.returncode != 0
    assert "invalid JSON" in rc.stderr
    assert "Traceback" not in rc.stderr


def test_missing_column_is_reported_not_raised(workdir):
    init_users(workdir)
    rc = run("insert", "users", '{"id": 1}', "--path", str(workdir))
    assert rc.returncode != 0
    assert "Traceback" not in rc.stderr


def test_non_snapdb_file_is_rejected(workdir):
    bad = workdir / "fake.snap"
    bad.write_bytes(b"NOTSNAP" + b"\x00" * 200)
    rc = run("count", "fake", "--path", str(workdir))
    assert rc.returncode != 0
    assert "not a SnapDB file" in rc.stderr


# ---- data survives a process boundary ------------------------------------


def test_data_written_by_one_process_is_read_by_the_next(workdir):
    """Flush is what makes this true; without it the test still passes on the
    same handle, so it must cross a process boundary to mean anything."""
    init_users(workdir)
    run("insert", "users", '{"id": 7, "name": "persisted", "email": "p@x.io"}', "--path", str(workdir))
    out = run("get", "users", "0", "--path", str(workdir)).stdout
    assert json.loads(out)["name"] == "persisted"
