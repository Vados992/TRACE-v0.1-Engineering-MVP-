# Desktop packaging

The desktop distribution preserves the TRACE v0.3 APIs and adds a Windows installer, isolated Docker Compose stack, app-window launcher, real source console, readiness endpoint, and filesystem evidence backend. The underlying platform remains an engineering MVP.

## Boundaries

- `Install TRACE.cmd` copies the snapshot to the Windows Known Folder Desktop and creates a `.lnk` that starts the complete local stack. Docker Desktop/Linux containers is an external prerequisite.
- Installation refuses to overwrite an existing destination. Secrets are generated per installation and never packaged.
- `compose.desktop.yml` publishes only loopback API. Databases are reachable only inside its Docker network.
- PostgreSQL and the evidence volume are authoritative. Neo4j can be rebuilt with `scripts/rebuild_graph.py`. Redis and OpenSearch are provisioned, but workers and a search projection are not implemented in v0.3.
- `/health` is liveness. `/ready` checks PostgreSQL migrations and writable evidence storage. `/api/v1/system/status` additionally checks Neo4j, Redis, OpenSearch. Upstream connectivity is assessed by a real import, not claimed by the inventory.
- Local filesystem evidence uses SHA-256 content keys, atomic no-overwrite publication, fsync and integrity verification. It is not WORM storage or an offsite backup. The original S3 backend remains available with `EVIDENCE_BACKEND=s3`.
- New desktop volumes do not silently import legacy Compose/S3 data. Do not change evidence backend on an existing database without migrating all objects and their URIs.
- No background mass download or scheduled synchronization. Initial bootstrap is bounded and records failure per source. Retry through the console.
- An unspecified remote server is not automatically provisioned. Linux startup and a Windows SSH tunnel launcher are included; server identity and access must come from the operator.

## Validation

`pytest -q` covers existing domain behavior plus filesystem concurrency, corruption detection, path traversal and readiness failures. The Windows CI job parses scripts using Windows PowerShell 5.1, installs to a path with spaces, inspects the real COM shortcut, and verifies no overwrite of existing settings. It does not run Docker Desktop on the user's machine.

The Linux desktop job runs the actual Compose file, all databases, every migration, real GLEIF/TED/Cellar imports, an evidence-backed path from real imported relationships, raw object hashes, then removes and recreates all containers while retaining volumes and compares the evidence set. External source unavailability causes the strict test to fail. The legacy Docker smoke also uses a synthetic relationship fixture and must not be represented as verification of that relationship in the real world.
