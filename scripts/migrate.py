import hashlib
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
MIGRATIONS = ROOT / "db" / "migrations"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://trace:trace_dev_only@localhost:5432/trace"
)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if not paths:
        raise SystemExit("no migrations found")

    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        # Session lock prevents two deployment jobs applying the same migration concurrently.
        conn.execute("SELECT pg_advisory_lock(7450208)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                 version TEXT PRIMARY KEY,
                 applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                 checksum TEXT NOT NULL
               )"""
        )
        applied = {
            row[0]: row[1]
            for row in conn.execute("SELECT version, checksum FROM schema_migrations")
        }
        for path in paths:
            data = path.read_bytes()
            canonical = data.replace(b"\r\n", b"\n")
            digest = checksum(canonical)
            version = path.name
            if version in applied:
                # Earlier versions hashed OS-specific checkout bytes. Accept only line-ending variants.
                if applied[version] not in {
                    digest,
                    checksum(data),
                    checksum(canonical.replace(b"\n", b"\r\n")),
                }:
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
        conn.execute("SELECT pg_advisory_unlock(7450208)")


if __name__ == "__main__":
    main()
