# snapdb-cli

Command-line interface for [SnapDB](https://github.com/hussain-alsaibai/snapdb) — the ultra-lightweight in-memory Python database.

## Install

```bash
pip install snapdb
# Or just copy snapdb_cli.py — zero dependencies
curl -O https://raw.githubusercontent.com/hussain-alsaibai/snapdb-cli/main/snapdb_cli.py
chmod +x snapdb_cli.py
```

## Quick Start

```bash
# Create a database with a schema
snapdb-cli init users id:i32,name:str,email:str --path ./data

# Insert records
snapdb-cli insert users '{"id": 1, "name": "alice", "email": "alice@example.com"}' --path ./data
snapdb-cli insert users '{"id": 2, "name": "bob", "email": "bob@example.com"}' --path ./data

# Read a record
snapdb-cli get users 0 --path ./data

# List all records
snapdb-cli list users --limit 100 --path ./data

# Count rows
snapdb-cli count users --path ./data

# Show schema
snapdb-cli schema users --path ./data

# Show stats
snapdb-cli stats users --path ./data

# Export to JSON
snapdb-cli export users --format json --path ./data

# Export to CSV
snapdb-cli export users --format csv --path ./data

# Run a benchmark
snapdb-cli benchmark users --ops 10000 --path ./data

# Watch for live changes
snapdb-cli watch users --interval 0.5 --path ./data
```

## Schema Types

| Type | Description | Python |
|------|-------------|--------|
| `i8`, `i16`, `i32`, `i64` | Signed integers | int |
| `u8`, `u16`, `u32`, `u64` | Unsigned integers | int |
| `f32`, `f64` | Floats | float |
| `str` | UTF-8 string | str |
| `bytes:N` | Fixed-size bytes | bytes |

## License

MIT
