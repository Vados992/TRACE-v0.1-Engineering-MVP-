# TRACE Desktop — validation record

Date: 28 September 2026. Tested application commit: `2eb337f5270997c5f7e7b1c125ffa5c4f35db669`.

The final packaging commit adds this report only. It does not change the tested application.

## Completed checks

| Check | Result | Evidence |
|---|---|---|
| Python tests | 24 passed | Local pytest and TRACE CI |
| API schema and Python compilation | Passed | TRACE CI; live OpenAPI 3.1, 22 paths |
| Windows installer, actual CMD entry point | Passed | Windows PowerShell 5.1 on a hosted Windows runner |
| Desktop folder, real Windows shortcut | Passed | COM shortcut inspected, installation path contains spaces |
| Existing settings protected | Passed | Repeat install refused, credentials preserved |
| Docker argument forwarding | Passed | Launcher preserves `-d` and `--build` |
| Edge UI workflow | Passed | Import, entity selection, search, Path Finder, provenance |
| Wide / compact layout | Passed | 1480px / 390px, no horizontal overflow; screenshots inspected |
| Clean desktop Docker stack | Passed | PostgreSQL, evidence volume, Neo4j, Redis and OpenSearch |
| SQL migrations | Passed | Five migrations applied |
| Live external ingestion | Passed | GLEIF, TED and EUR-Lex / Cellar |
| Real canonical relationship path | Passed | Path Finder and provenance endpoint on imported relationships |
| Evidence integrity | Passed | Five raw evidence objects, every SHA-256 verified |
| Persistence | Passed | All containers removed/recreated; identical evidence set, readable data and path |
| Legacy S3 development stack | Passed | Separate existing Docker smoke workflow |

## Reproducible evidence

- [Desktop stack and Windows / Edge checks](https://github.com/Vados992/TRACE-v0.1-Engineering-MVP-/actions/runs/36449924338)
- [Python CI](https://github.com/Vados992/TRACE-v0.1-Engineering-MVP-/actions/runs/36449930750)
- [Legacy Docker smoke](https://github.com/Vados992/TRACE-v0.1-Engineering-MVP-/actions/runs/36449930585)
- [Changes in GitHub](https://github.com/Vados992/TRACE-v0.1-Engineering-MVP-/pull/1)

Browser UI checks use explicitly labeled test responses, not live company data. Live source and database checks are separate and use real endpoints. The original legacy smoke contains an isolated synthetic relationship; the new desktop smoke verifies an actual imported canonical relationship.

## Observed sample and limits

The bounded live sample produced two GLEIF accounting-parent relationships, six TED procurement relationships and 307 Cellar legal relationships. These are sample results, not a census of the registries. The TED sample created no money-flow rows; it does not validate a real banking payment or full financial coverage. Source responses can change after testing.

No code in this task was executed on the user's Windows computer. The full container stack was tested on Linux GitHub runners, and installation plus UI were tested on a Windows runner. Docker Desktop / WSL compatibility, local port availability and resources on the user's own machine remain to be checked by running the installer.

No remote server was provisioned or contacted: no server address or access configuration was supplied. The package includes a server startup script and an SSH tunnel launcher.

Lobbying data still requires a standardized official-file import. Redis/OpenSearch are available infrastructure without an ingestion worker or populated search projection in v0.3. The system remains an engineering MVP, not a certified public production deployment or a complete live mirror of every financial and political source.
