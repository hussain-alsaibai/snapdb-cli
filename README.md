# snapdb-cli

Command-line interface for [SnapDB](https://github.com/hussain-alsaibai/snapdb) — the ultra-lightweight in-memory Python database.

[![CI](https://github.com/hussain-alsaibai/snapdb-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/hussain-alsaibai/snapdb-cli/actions/workflows/ci.yml)

## Install

```bash
pip install snapdb        # the library
# then use the CLI directly — it is a single file, no dependencies of its own
curl -O https://raw.githubusercontent.com/hussain-alsaibai/snapdb-cli/main/snapdb_cli.py
chmod +x snapdb_cli.py
```

## Schema syntax

```
col:TYPE[,col:TYPE...]
```

TYPE is one of the fixed-width dtypes SnapDB actually stores:

| Type | Meaning |
|---|---|
| `i8` `i16` `i32` `i64` | signed integers |
| `u8` `u16` `u32` `u64` | unsigned integers |
| `f32` `f64` | floats |
| `bool` | 1 byte |
| `bytes:N` | UTF-8 text, **padded to N bytes** — N is required |

**There is no `str` type.** SnapDB stores text as a fixed-width `bytes:N`
column, so the width is part of the schema. A value longer than N is truncated
to N bytes, so size the column for the longest value you will store.

```bash
snapdb-cli init users id:i32,name:bytes:16,email:bytes:32
```

If you write `name:str` the CLI tells you what to write instead rather than
failing deep inside the encoder.

## Quick start

```bash
# Create a database with a schema
snapdb-cli init users id:i32,name:bytes:16,email:bytes:32 --path ./data

# Insert records (one object, or an array of objects)
snapdb-cli insert users '{"id": 1, "name": "alice", "email": "alice@example.com"}' --path ./data
snapdb-cli insert users '{"id": 2, "name": "bob", "email": "bob@example.com"}' --path ./data

# Read a row by its row id (0-based)
snapdb-cli get users 0 --path ./data

# List rows
snapdb-cli list users --limit 100 --path ./data

# Count rows
snapdb-cli count users --path ./data

# Show the schema (and a spec you can paste back into init)
snapdb-cli schema users --path ./data

# File size and row count
snapdb-cli stats users --path ./data

# Export
snapdb-cli export users --format json  --path ./data
snapdb-cli export users --format csv   --path ./data
snapdb-cli export users --format ndjson --path ./data
```

Real output from that sequence:

```
$ snapdb-cli init users id:i32,name:bytes:16,email:bytes:32 --path /tmp/sdbtest
Created database 'users' at /tmp/sdbtest/users.snap
  Columns: id:i32, name:bytes:16, email:bytes:32

$ snapdb-cli list users --path /tmp/sdbtest
Total rows: 2
  [0] {"id": 1, "name": "alice", "email": "alice@example.com"}
  [1] {"id": 2, "name": "bob", "email": "bob@example.com"}

$ snapdb-cli schema users --path /tmp/sdbtest
Schema for 'users':
  id: i32
  name: bytes:16
  email: bytes:32

As a spec:
  id:i32,name:bytes:16,email:bytes:32

$ snapdb-cli stats users --path /tmp/sdbtest
Database: users
Path:     /tmp/sdbtest/users.snap
Rows:     2
On disk:  4476 bytes
Columns:  3
  - id: i32
  - name: bytes:16
  - email: bytes:32
```

## Other commands

```bash
snapdb-cli delete users 1 --path ./data          # delete row by row id
snapdb-cli benchmark users --ops 1000 --path ./data
snapdb-cli watch users --interval 1 --path ./data   # poll and report row-count changes
```

`benchmark` writes to a scratch database named `<db>.bench.snap` next to the
original, and leaves it there. Delete it when you are done with it.

`benchmark` output, measured on a 3-column schema (one run, not a median):

```
Benchmark (1000 ops, 3 columns):
  Insert:      168,403 ops/sec  (0.0059s)
  Read:        403,290 ops/sec  (0.0025s)
  Scratch db: /tmp/sdbtest/users.bench.snap (delete it when done)
```

Your numbers will differ; treat them as a smoke test, not a leaderboard. For a
real benchmark run the library's own harness with a warm page cache.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | command failed (missing db, bad schema, rejected row, missing row) |
| 130 | interrupted |

Errors go to stderr with a one-line explanation. The CLI never prints a
traceback for a user mistake.

## Notes on behaviour

**`init` refuses to overwrite.** An existing `<name>.snap` is an error, not a
silent reset.

**Writes are flushed before exit,** so the next invocation sees them. SnapDB
holds one handle per file per process, which is why every command is its own
process.

**Text is padded to the declared width,** so `bytes:16` holds at most 16
UTF-8 bytes and longer values are truncated without a warning. Choose widths
deliberately.

## Development

```bash
python -m pytest -q
```

Tests drive the real CLI as a subprocess, including a job that runs the
README's quick start verbatim so documentation drift fails CI.

## License

MIT — see [LICENSE](LICENSE).
