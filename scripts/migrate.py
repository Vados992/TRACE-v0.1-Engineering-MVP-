import hashlib
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db" / "migrations"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://trace:trace_dev_only@localhost:5432/trace")


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if not paths:
        raise SystemExit("no migrations found")

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                 version TEXT PRIMARY KEY,
                 applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                 checksum TEXT NOT NULL
               )"""
        )
        applied = {row[0]: row[1] for row in conn.execute("SELECT version, checksum FROM schema_migrations")}
        for path in paths:
            data = path.read_bytes()
            digest = checksum(data)
            version = path.name
            if version in applied:
                if applied[version] != digest:
                    raise SystemExit(f"migration checksum mismatch: {version}")
                print(f"skip {version}")
                continue
            print(f"apply {version}")
            with conn.transaction():
                conn.execute(data.decode("utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                    (version, digest),
                )


if __name__ == "__main__":
    main()
