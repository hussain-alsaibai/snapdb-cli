#!/usr/bin/env python3
"""
snapdb-cli — Command-line interface for SnapDB.
Interact with SnapDB databases directly from your terminal.

Usage:
    snapdb-cli init <name> <schema> [--path DIR]
    snapdb-cli insert <db> <json> [--path DIR]
    snapdb-cli get <db> <id> [--path DIR]
    snapdb-cli list <db> [--limit N] [--offset N] [--path DIR]
    snapdb-cli count <db> [--path DIR]
    snapdb-cli delete <db> <id> [--path DIR]
    snapdb-cli stats <db> [--path DIR]
    snapdb-cli schema <db> [--path DIR]
    snapdb-cli export <db> [--format json|csv|ndjson] [--path DIR]
    snapdb-cli benchmark <db> [--ops N] [--path DIR]
    snapdb-cli watch <db> [--interval S] [--path DIR]

Schema syntax
-------------
    col:TYPE[,col:TYPE...]

TYPE is one of the fixed-width dtypes SnapDB supports:

    i8 i16 i32 i64   signed integers
    u8 u16 u32 u64   unsigned integers
    f32 f64          floats
    bool             1 byte
    bytes:N          UTF-8 string, padded to N bytes (N is required)

There is no bare `str` or `string` type. SnapDB stores text as a fixed-width
`bytes:N` column, so the width is part of the schema. A value longer than N
is silently truncated to N bytes, so size the column for the longest value
you will store.

Example:

    snapdb-cli init users id:i32,name:bytes:16,email:bytes:32
"""

import argparse
import csv
import io
import json
import os
import struct
import sys
import time

from snapdb import SnapDB, Schema, ColumnDef


VALID_DTYPES = {
    "i8", "i16", "i32", "i64",
    "u8", "u16", "u32", "u64",
    "f32", "f64",
    "bool",
}


def _db_path(name: str, path: str = ".") -> str:
    return os.path.join(path, name + ".snap")


# SnapDB stores the schema inside the file header, so a reader needs the
# schema to construct a SnapDB but cannot get the schema without opening the
# file. There is no SnapDB.open() classmethod: the constructor takes the
# schema and loads the existing pages when the path is already populated.
# So the CLI reads the header itself and rebuilds the schema from it.
_HEADER_FMT = "<4sHHIQ"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_MAGIC = b"SNAP"


def read_schema(db_path: str) -> Schema:
    """Rebuild a Schema from a .snap file's header."""
    with open(db_path, "rb") as fh:
        header = fh.read(_HEADER_SIZE)
        if len(header) < _HEADER_SIZE:
            sys.exit("Error: " + db_path + " is too short to be a SnapDB file")
        magic, _version, _page_size, _flags, schema_offset = struct.unpack(
            _HEADER_FMT, header
        )
        if magic != _MAGIC:
            sys.exit(
                "Error: " + db_path + " is not a SnapDB file (bad magic "
                + repr(magic) + ")"
            )
        fh.seek(_HEADER_SIZE)
        raw = fh.read(schema_offset - _HEADER_SIZE)
    try:
        return Schema.from_json(json.loads(raw.decode("utf-8")))
    except (ValueError, KeyError, TypeError) as exc:
        sys.exit("Error: could not read the schema from " + db_path + " - " + str(exc))


def get_db(name: str, path: str = ".") -> SnapDB:
    """Open an existing database, or exit with a clear message."""
    db_path = _db_path(name, path)
    if not os.path.exists(db_path):
        sys.exit("Error: database '" + name + "' not found at " + db_path)
    return SnapDB(db_path, read_schema(db_path))


def parse_schema(spec: str):
    """Parse `col:type,col:type` into a Schema.

    Rejects unknown dtypes here rather than letting a KeyError escape from
    inside the encoder, and rejects `bytes` without a width because that is
    the mistake a user makes when they write `str`.
    """
    columns = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            sys.exit(
                "Error: invalid schema part " + repr(part)
                + ". Use col:type, e.g. id:i32,name:bytes:16"
            )
        col_name, col_type = part.split(":", 1)
        col_name = col_name.strip()
        col_type = col_type.strip()
        if not col_name:
            sys.exit("Error: empty column name in " + repr(part))
        if col_type in ("str", "string", "text", "varchar"):
            sys.exit(
                "Error: " + repr(col_type) + " is not a SnapDB dtype. Text is "
                "stored as a fixed-width bytes:N column, e.g. "
                + col_name + ":bytes:32"
            )
        if col_type == "bytes" or col_type.startswith("bytes:"):
            if col_type == "bytes":
                sys.exit(
                    "Error: bytes needs a width, e.g. "
                    + col_name + ":bytes:32. SnapDB columns are fixed-width."
                )
            try:
                width = int(col_type.split(":", 1)[1])
            except ValueError:
                sys.exit("Error: bytes width must be an integer in " + repr(part))
            if width <= 0:
                sys.exit("Error: bytes width must be positive in " + repr(part))
        elif col_type not in VALID_DTYPES:
            sys.exit(
                "Error: unknown dtype " + repr(col_type) + " in " + repr(part)
                + ". Valid: " + ", ".join(sorted(VALID_DTYPES)) + ", bytes:N"
            )
        columns.append(ColumnDef(col_name, col_type))
    if not columns:
        sys.exit("Error: schema declares no columns")
    return Schema(columns)


def cmd_init(args):
    """Create a new SnapDB."""
    schema = parse_schema(args.schema)
    db_path = _db_path(args.name, args.path)
    if os.path.exists(db_path):
        sys.exit("Error: database already exists at " + db_path)
    db = SnapDB(db_path, schema)
    db.flush()
    print("Created database '" + args.name + "' at " + db_path)
    print("  Columns: " + ", ".join(c.name + ":" + c.dtype for c in schema.columns))
    db.close()
    return 0


def cmd_insert(args):
    """Insert one JSON object, or a JSON array of objects."""
    db = get_db(args.db, args.path)
    try:
        payload = json.loads(args.json)
    except json.JSONDecodeError as exc:
        sys.exit("Error: invalid JSON - " + str(exc))
    rows = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(r, dict) for r in rows):
        sys.exit("Error: expected a JSON object or an array of objects")
    ids = []
    for row in rows:
        try:
            ids.append(db.insert(row))
        except (KeyError, ValueError) as exc:
            db.close()
            sys.exit("Error: row rejected - " + str(exc))
    db.flush()
    db.close()
    for row_id in ids:
        print("Inserted row " + str(row_id))
    return 0


def cmd_get(args):
    """Get a record by row id."""
    db = get_db(args.db, args.path)
    record = db.get(args.id)
    db.close()
    if record is None:
        print("Row " + str(args.id) + " not found")
        return 1
    print(json.dumps(record, indent=2, default=str))
    return 0


def cmd_list(args):
    """List records by row id."""
    db = get_db(args.db, args.path)
    total = len(db)
    offset = args.offset or 0
    limit = args.limit if args.limit is not None else 100
    print("Total rows: " + str(total))
    shown = 0
    for i in range(min(offset + limit, total)):
        if i < offset:
            continue
        row = db.get(i)
        if row is not None:
            print("  [" + str(i) + "] " + json.dumps(row, default=str))
            shown += 1
    db.close()
    if shown == 0:
        if total == 0:
            print("(no rows)")
        else:
            print("(empty result - offset beyond range)")
    return 0


def cmd_count(args):
    """Count rows."""
    db = get_db(args.db, args.path)
    count = len(db)
    db.close()
    print("Row count: " + str(count))
    return 0


def cmd_delete(args):
    """Delete a row by id."""
    db = get_db(args.db, args.path)
    if args.id < 0 or args.id >= len(db):
        db.close()
        sys.exit("Error: row " + str(args.id) + " does not exist")
    db.delete(args.id)
    db.flush()
    db.close()
    print("Deleted row " + str(args.id))
    return 0


def cmd_stats(args):
    """Show database stats."""
    db = get_db(args.db, args.path)
    db_path = str(db.path)
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    print("Database: " + args.db)
    print("Path:     " + db_path)
    print("Rows:     " + str(len(db)))
    print("On disk:  " + str(size) + " bytes")
    print("Columns:  " + str(len(db.schema.columns)))
    for col in db.schema.columns:
        print("  - " + col.name + ": " + col.dtype)
    db.close()
    return 0


def cmd_schema(args):
    """Show the database schema, as a spec you can paste back into init."""
    db = get_db(args.db, args.path)
    print("Schema for '" + args.db + "':")
    for col in db.schema.columns:
        print("  " + col.name + ": " + col.dtype)
    print("\nAs a spec:")
    print("  " + ",".join(c.name + ":" + c.dtype for c in db.schema.columns))
    db.close()
    return 0


def _all_rows(db):
    rows = []
    for i in range(len(db)):
        row = db.get(i)
        if row is not None:
            rows.append(row)
    return rows


def cmd_export(args):
    """Export the database to JSON, NDJSON or CSV."""
    db = get_db(args.db, args.path)
    records = _all_rows(db)
    fieldnames = [c.name for c in db.schema.columns]
    db.close()

    if args.format == "json":
        print(json.dumps(records, indent=2, default=str))
    elif args.format == "ndjson":
        for record in records:
            print(json.dumps(record, default=str))
    elif args.format == "csv":
        # Always emit the header, even for an empty table: a headerless CSV
        # is read downstream as a file with no columns.
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        sys.stdout.write(out.getvalue())
    return 0


def cmd_benchmark(args):
    """Run a quick insert and read benchmark against a scratch database."""
    src = get_db(args.db, args.path)
    scratch_path = _db_path(args.db + ".bench", args.path)
    if os.path.exists(scratch_path):
        os.unlink(scratch_path)

    ops = args.ops
    scratch = SnapDB(scratch_path, src.schema)
    # Build a row with every column at its type's default, so the benchmark
    # measures SnapDB rather than a KeyError.
    template = {}
    for col in src.schema.columns:
        if col.dtype == "bool":
            template[col.name] = False
        elif col.dtype.startswith("bytes"):
            template[col.name] = "x"
        elif col.dtype.startswith("f"):
            template[col.name] = 0.5
        else:
            template[col.name] = 1

    start = time.perf_counter()
    for _ in range(ops):
        scratch.insert(template)
    insert_s = time.perf_counter() - start
    scratch.flush()

    # SnapDB allows one handle per file per process, so read through the same
    # handle that wrote. Reopening here would raise, correctly.
    start = time.perf_counter()
    for i in range(ops):
        scratch.get(i % ops)
    read_s = time.perf_counter() - start

    src.close()
    scratch.close()

    print("Benchmark (" + str(ops) + " ops, " + str(len(template)) + " columns):")
    print("  Insert: {:>12,.0f} ops/sec  ({:.4f}s)".format(
        ops / insert_s if insert_s else 0, insert_s))
    print("  Read:   {:>12,.0f} ops/sec  ({:.4f}s)".format(
        ops / read_s if read_s else 0, read_s))
    print("  Scratch db: " + scratch_path + " (delete it when done)")
    return 0


def cmd_watch(args):
    """Poll a database and print the row count when it changes."""
    db = get_db(args.db, args.path)
    last = len(db)
    print("Watching '" + args.db + "' - press Ctrl+C to stop")
    print("Initial row count: " + str(last))
    while True:
        time.sleep(args.interval)
        db_path = str(db.path)
        db.close()
        db = SnapDB(db_path, read_schema(db_path))
        current = len(db)
        if current != last:
            delta = current - last
            print("  [" + time.strftime("%H:%M:%S") + "] "
                  + ("+" if delta > 0 else "") + str(delta)
                  + " rows (total: " + str(current) + ")")
            last = current


def build_parser():
    parser = argparse.ArgumentParser(
        description="snapdb-cli - CLI for SnapDB in-memory databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, **kwargs):
        p = sub.add_parser(name, **kwargs)
        p.add_argument("--path", default=".", help="Directory holding the .snap file")
        return p

    p = add("init", help="Create a new SnapDB")
    p.add_argument("name", help="Database name")
    p.add_argument("schema", help="Schema as col:type,... e.g. id:i32,name:bytes:16")

    p = add("insert", help="Insert a JSON record or array of records")
    p.add_argument("db")
    p.add_argument("json", help="A JSON object or array of objects")

    p = add("get", help="Get a row by id")
    p.add_argument("db")
    p.add_argument("id", type=int)

    p = add("list", help="List rows")
    p.add_argument("db")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--offset", type=int, default=0)

    for name, help_text in (
        ("count", "Count rows"),
        ("stats", "Show database statistics"),
        ("schema", "Show the schema"),
    ):
        p = add(name, help=help_text)
        p.add_argument("db")

    p = add("delete", help="Delete a row by id")
    p.add_argument("db")
    p.add_argument("id", type=int)

    p = add("export", help="Export to JSON/NDJSON/CSV")
    p.add_argument("db")
    p.add_argument("--format", default="json", choices=["json", "ndjson", "csv"])

    p = add("benchmark", help="Run a quick insert/read benchmark")
    p.add_argument("db")
    p.add_argument("--ops", type=int, default=1000)

    p = add("watch", help="Poll and report row-count changes")
    p.add_argument("db")
    p.add_argument("--interval", type=float, default=1.0)

    return parser


COMMANDS = {
    "init": cmd_init,
    "insert": cmd_insert,
    "get": cmd_get,
    "list": cmd_list,
    "count": cmd_count,
    "delete": cmd_delete,
    "stats": cmd_stats,
    "schema": cmd_schema,
    "export": cmd_export,
    "benchmark": cmd_benchmark,
    "watch": cmd_watch,
}


def main():
    args = build_parser().parse_args()
    try:
        return COMMANDS[args.cmd](args)
    except KeyboardInterrupt:
        if args.cmd == "watch":
            print("\nStopped.")
            return 0
        return 130
    except Exception as exc:
        sys.exit("Error: " + str(exc))


if __name__ == "__main__":
    sys.exit(main())
