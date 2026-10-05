#!/bin/sh
set -eu
latest="$(find /backups -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
[ -n "$latest" ] || { echo "no backup found" >&2; exit 1; }
(
  cd "$latest"
  sha256sum -c manifest.sha256
  tar -tf evidence.tar >/dev/null
)
pg_restore --exit-on-error --no-owner --no-privileges -h restore-postgres -U trace_restore -d trace_restore "$latest/database.dump"
migrations="$(psql -h restore-postgres -U trace_restore -d trace_restore -Atc 'SELECT count(*) FROM schema_migrations')"
[ "$migrations" -ge 11 ] || { echo "restore missing migrations" >&2; exit 1; }
broken="$(psql -h restore-postgres -U trace_restore -d trace_restore -Atc "
WITH ordered AS (
  SELECT id,previous_hash,event_hash,
         lag(event_hash) OVER (ORDER BY id) AS prior_hash
  FROM audit_events
)
SELECT count(*) FROM ordered
WHERE previous_hash <> COALESCE(prior_hash, repeat('0',64));")"
[ "$broken" = "0" ] || { echo "restored audit chain is broken" >&2; exit 1; }
echo "restore drill passed: $latest ($migrations migrations)"
