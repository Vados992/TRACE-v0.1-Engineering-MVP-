"""Persist PostgreSQL commit receipts before backup and after external SQL imports."""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    count = conn.execute("SELECT trace_finalize_temporal_commits()").fetchone()[0]
print(f"Persisted {count} temporal commit receipts")
