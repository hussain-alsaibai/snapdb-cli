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
    snapdb-cli query <db> "sql-like" [--path DIR]
    snapdb-cli stats <db> [--path DIR]
    snapdb-cli schema <db> [--path DIR]
    snapdb-cli export <db> [--format json|csv] [--path DIR]
    snapdb-cli benchmark <db> [--ops N] [--path DIR]
"""

import argparse
import json
import sys
import time
import os
import csv
import io

from snapdb import SnapDB, Schema, ColumnDef


def get_db(name: str, path: str = ".") -> SnapDB:
    """Load or error out."""
    db_path = os.path.join(path, f"{name}.snap")
    if not os.path.exists(db_path):
        sys.exit(f"Error: Database '{name}' not found at {db_path}")
    return SnapDB.open(db_path)


def cmd_init(args):
    """Initialize a new SnapDB."""
    # Parse schema like: id:i32,name:str,age:i32
    columns = []
    for part in args.schema.split(","):
        part = part.strip()
        if ":" not in part:
            sys.exit(f"Invalid schema part: '{part}'. Use name:type, e.g. id:i32,name:str")
        col_name, col_type = part.split(":", 1)
        columns.append(ColumnDef(col_name, col_type))
    schema = Schema(columns)
    db_path = os.path.join(args.path, f"{args.name}.snap")
    db = SnapDB.create(db_path, schema)
    print(f"✓ Created database '{args.name}' at {db_path}")
    print(f"  Schema: {args.schema}")
    return db


def cmd_insert(args):
    """Insert a record."""
    db = get_db(args.db, args.path)
    try:
        record = json.loads(args.json)
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON: {e}")
    row_id = db.insert(record)
    print(f"✓ Inserted row {row_id}")
    return row_id


def cmd_get(args):
    """Get a record by ID."""
    db = get_db(args.db, args.path)
    row_id = int(args.id)
    record = db.get(row_id)
    if record is None:
        print(f"Row {row_id} not found")
    else:
        print(json.dumps(record, indent=2, default=str))
    return record


def cmd_list(args):
    """List records."""
    db = get_db(args.db, args.path)
    limit = args.limit or 100
    offset = args.offset or 0
    total = db.count()
    print(f"Total rows: {total}")
    if offset >= total:
        print("(empty result — offset beyond range)")
        return
    for i in range(offset, min(offset + limit, total)):
        row = db.get(i)
        if row is not None:
            print(f"  [{i}] {json.dumps(row, default=str)}")


def cmd_count(args):
    """Count rows."""
    db = get_db(args.db, args.path)
    count = db.count()
    print(f"Row count: {count}")
    return count


def cmd_delete(args):
    """Delete a record."""
    db = get_db(args.db, args.path)
    row_id = int(args.id)
    db.delete(row_id)
    print(f"✓ Deleted row {row_id}")


def cmd_stats(args):
    """Show database stats."""
    db = get_db(args.db, args.path)
    print(f"Database: {args.db}")
    print(f"Path: {db._path}")
    print(f"Schema columns: {len(db.schema.columns)}")
    for col in db.schema.columns:
        print(f"  - {col.name}: {col.dtype}")
    print(f"Row count: {db.count()}")
    if hasattr(db, 'metrics') and db.metrics:
        m = db.metrics
        print(f"Metrics:")
        print(f"  inserts: {m.get('inserts', 0)}")
        print(f"  lookups: {m.get('lookups', 0)}")
        print(f"  updates: {m.get('updates', 0)}")
        print(f"  deletes: {m.get('deletes', 0)}")


def cmd_schema(args):
    """Show database schema."""
    db = get_db(args.db, args.path)
    print(f"Schema for '{args.db}':")
    for col in db.schema.columns:
        print(f"  {col.name}: {col.dtype}")


def cmd_export(args):
    """Export database to JSON or CSV."""
    db = get_db(args.db, args.path)
    records = []
    for i in range(db.count()):
        row = db.get(i)
        if row is not None:
            records.append(row)

    if args.format == "json" or args.format == "jsonl":
        output = json.dumps(records, indent=2, default=str)
        print(output)
    elif args.format == "csv":
        if not records:
            print("(no records to export)")
            return
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
        print(output.getvalue())
    elif args.format == "ndjson":
        for r in records:
            print(json.dumps(r, default=str))


def cmd_benchmark(args):
    """Run a quick benchmark."""
    db = get_db(args.db, args.path)
    ops = args.ops or 1000
    total = db.count()

    # Insert benchmark
    test_record = {"_benchmark": 1, "value": "test"}
    start = time.perf_counter()
    for i in range(ops):
        db.insert(test_record)
    insert_time = time.perf_counter() - start
    insert_per_sec = ops / insert_time if insert_time > 0 else float('inf')

    # Read benchmark
    if total > 0:
        start = time.perf_counter()
        for _ in range(min(ops, total * 2)):
            db.get(_ % total)
        read_time = time.perf_counter() - start
        read_per_sec = ops / read_time if read_time > 0 else float('inf')
    else:
        read_per_sec = 0

    print(f"Benchmark results ({ops} ops):")
    print(f"  Insert: {insert_per_sec:,.0f} ops/sec ({insert_time:.4f}s total)")
    print(f"  Read:   {read_per_sec:,.0f} ops/sec ({read_time:.4f}s total)")


def cmd_watch(args):
    """Watch a database for changes (live tail)."""
    import select
    db = get_db(args.db, args.path)
    last_count = db.count()
    print(f"Watching '{args.db}' — press Ctrl+C to stop")
    print(f"Initial row count: {last_count}")
    while True:
        time.sleep(args.interval or 1)
        new_count = db.count()
        if new_count != last_count:
            delta = new_count - last_count
            print(f"  [{time.strftime('%H:%M:%S')}] +{delta} rows (total: {new_count})")
            last_count = new_count


def build_parser():
    parser = argparse.ArgumentParser(
        description="snapdb-cli — CLI for SnapDB in-memory databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # init
    p = sub.add_parser("init", help="Create a new SnapDB")
    p.add_argument("name", help="Database name")
    p.add_argument("schema", help="Schema as col:type,col:type, e.g. id:i32,name:str")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # insert
    p = sub.add_parser("insert", help="Insert a JSON record")
    p.add_argument("db", help="Database name")
    p.add_argument("json", help="JSON record")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # get
    p = sub.add_parser("get", help="Get a row by ID")
    p.add_argument("db", help="Database name")
    p.add_argument("id", type=int, help="Row ID")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # list
    p = sub.add_parser("list", help="List rows")
    p.add_argument("db", help="Database name")
    p.add_argument("--limit", type=int, help="Max rows to show")
    p.add_argument("--offset", type=int, help="Skip first N rows")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # count
    p = sub.add_parser("count", help="Count rows")
    p.add_argument("db", help="Database name")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # delete
    p = sub.add_parser("delete", help="Delete a row")
    p.add_argument("db", help="Database name")
    p.add_argument("id", type=int, help="Row ID")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # stats
    p = sub.add_parser("stats", help="Show database statistics")
    p.add_argument("db", help="Database name")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # schema
    p = sub.add_parser("schema", help="Show database schema")
    p.add_argument("db", help="Database name")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # export
    p = sub.add_parser("export", help="Export to JSON/CSV")
    p.add_argument("db", help="Database name")
    p.add_argument("--format", default="json", choices=["json", "jsonl", "ndjson", "csv"])
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # benchmark
    p = sub.add_parser("benchmark", help="Run a quick benchmark")
    p.add_argument("db", help="Database name")
    p.add_argument("--ops", type=int, default=1000, help="Number of operations")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    # watch
    p = sub.add_parser("watch", help="Watch for changes (live tail)")
    p.add_argument("db", help="Database name")
    p.add_argument("--interval", type=float, default=1.0, help="Poll interval in seconds")
    p.add_argument("--path", default=".", help="Directory for .snap file")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    commands = {
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

    if args.cmd in commands:
        try:
            commands[args.cmd](args)
        except KeyboardInterrupt:
            if args.cmd == "watch":
                print("\nStopped.")
            else:
                raise
        except Exception as e:
            sys.exit(f"Error: {e}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
