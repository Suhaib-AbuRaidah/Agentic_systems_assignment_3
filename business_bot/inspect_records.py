"""Owner-only CLI: inspect local SQLite records, never an app endpoint."""
import argparse
import json
from app import database_path
from storage import Storage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", choices=["leads", "feedback", "events"])
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(Storage(database_path()).records(args.table, args.limit), indent=2, ensure_ascii=False))
