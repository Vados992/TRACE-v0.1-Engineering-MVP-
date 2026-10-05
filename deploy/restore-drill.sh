#!/bin/sh
set -eu
latest="$(find /backups -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
[ -n "$latest" ] || { echo "no backup found" >&2; exit 1; }
(
  cd "$latest"
  sha256sum -c manifest.sha256
)
mkdir -p /tmp/evidence
tar -C /tmp/evidence -xf "$latest/evidence.tar"
pg_restore --exit-on-error --no-owner --no-privileges -h restore-postgres -U trace_restore -d trace_restore "$latest/database.dump"
migrations="$(psql -h restore-postgres -U trace_restore -d trace_restore -Atc 'SELECT count(*) FROM schema_migrations')"
[ "$migrations" -ge 12 ] || { echo "restore missing migrations" >&2; exit 1; }

missing=0
psql -h restore-postgres -U trace_restore -d trace_restore -Atc \
  "SELECT object_key FROM raw_artifacts ORDER BY object_key" > /tmp/object-keys
while IFS= read -r key; do
  [ -z "$key" ] && continue
  if [ ! -f "/tmp/evidence/$key" ]; then
    echo "missing restored evidence object: $key" >&2
    missing=$((missing + 1))
  fi
done < /tmp/object-keys
[ "$missing" = "0" ] || exit 1

broken="$(psql -h restore-postgres -U trace_restore -d trace_restore -Atc "
WITH ordered AS (
  SELECT id,occurred_at,actor,action,resource,details,previous_hash,event_hash,
         lag(event_hash) OVER (ORDER BY id) AS prior_hash
  FROM audit_events
), checked AS (
  SELECT *,
    encode(digest(previous_hash || jsonb_build_array(
      id, occurred_at AT TIME ZONE 'UTC', actor, action, resource, details
    )::text, 'sha256'), 'hex') AS calculated_hash
  FROM ordered
)
SELECT count(*) FROM checked
WHERE previous_hash <> COALESCE(prior_hash, repeat('0',64))
   OR event_hash <> calculated_hash;")"
[ "$broken" = "0" ] || { echo "restored audit chain is broken" >&2; exit 1; }
echo "restore drill passed: $latest ($migrations migrations, evidence complete, audit chain valid)"
