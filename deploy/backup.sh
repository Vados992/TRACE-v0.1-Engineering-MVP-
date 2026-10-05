#!/bin/sh
set -eu
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="/backups/$stamp"
mkdir -p "$target"
pg_dump -Fc -h postgres -U trace_owner -d trace -f "$target/database.dump"
tar -C /evidence -cf "$target/evidence.tar" .
(
  cd "$target"
  sha256sum database.dump evidence.tar > manifest.sha256
  printf '{"created_at":"%s","database":"trace","format":"pg_dump_custom+evidence_tar"}\n' "$stamp" > metadata.json
)
echo "$target"
