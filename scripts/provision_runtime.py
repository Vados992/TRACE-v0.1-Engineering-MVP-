"""Use the migration-owner DSN once. Password never appears in argv or logs."""

import os

import psycopg
from dotenv import load_dotenv
from psycopg import sql

load_dotenv()


def main():
    dsn = os.environ["MIGRATION_DATABASE_URL"]
    password = os.environ["TRACE_RUNTIME_PASSWORD"]
    if len(password) < 32:
        raise SystemExit("Runtime password must have at least 32 characters")
    with psycopg.connect(dsn, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='trace_runtime'").fetchone():
            conn.execute("CREATE ROLE trace_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        conn.execute(sql.SQL("ALTER ROLE trace_runtime PASSWORD {}").format(sql.Literal(password)))
        database = conn.execute("SELECT current_database()").fetchone()[0]
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO trace_runtime").format(
                sql.Identifier(database)
            )
        )
        conn.execute("GRANT USAGE ON SCHEMA public TO trace_runtime")
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO trace_runtime"
        )
        conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO trace_runtime")
        conn.execute("REVOKE ALL ON schema_migrations FROM trace_runtime")
        conn.execute("GRANT SELECT ON schema_migrations TO trace_runtime")
        conn.execute("REVOKE UPDATE,DELETE,TRUNCATE ON audit_events FROM trace_runtime")
        conn.execute("REVOKE UPDATE,DELETE,TRUNCATE ON case_events FROM trace_runtime")
        for table in (
            "temporal_versions",
            "temporal_commits",
            "temporal_control",
            "temporal_pending",
        ):
            conn.execute(
                sql.SQL("REVOKE ALL ON {} FROM trace_runtime").format(sql.Identifier(table))
            )
            conn.execute(
                sql.SQL("GRANT SELECT ON {} TO trace_runtime").format(sql.Identifier(table))
            )
        conn.execute("REVOKE ALL ON SEQUENCE temporal_versions_version_id_seq FROM trace_runtime")
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    print("trace_runtime provisioned; schema owner retained for migrations only")


if __name__ == "__main__":
    main()
