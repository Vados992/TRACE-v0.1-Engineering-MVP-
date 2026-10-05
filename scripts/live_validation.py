"""Opt-in verification against public sources. Saves aggregates, never personal names or tokens."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("TRACE_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--sources", nargs="+", default=["ocds", "openownership"])
    parser.add_argument("--output", default=".artifacts/live-validation.json")
    args = parser.parse_args()
    token = os.getenv("TRACE_API_TOKEN", "trace-dev-analyst-only")
    headers = {"Authorization": "Bearer " + token}
    report = {
        "synthetic": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "limitations": [
            "Cross-source comparability is never inferred automatically; it requires an explicit semantic contract.",
            "Open Ownership is the 2025-03-11 publisher snapshot, not current Companies House.",
            "Source assertions are not legal conclusions; public release requires independent review.",
        ],
    }
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=240) as client:
        client.get("/ready").raise_for_status()
        for source in args.sources:
            if source in {"ocds", "openownership", "bods", "ppds"}:
                response = client.post(
                    "/api/internal/connectors/fetch",
                    json={
                        "source": source,
                        "limit": 3,
                        "license": "https://creativecommons.org/publicdomain/zero/1.0/"
                        if source == "openownership"
                        else "Publisher license retained in raw source; operator must validate reuse",
                        "legal_basis": "Operator-authorized internal technical evaluation of public register data; no publication",
                    },
                )
            elif source == "unsdg":
                response = client.post(
                    "/api/internal/sdg/import",
                    json={
                        "query": {
                            "series_code": "EG_ELC_ACCS",
                            "area_codes": [620],
                            "time_period_start": 2020,
                            "time_period_end": 2025,
                            "page_size": 100,
                            "max_pages": 5,
                        },
                        "legal_basis": "Operator-authorized validation of official public UN SDG statistics",
                    },
                )
            elif source in {"eurostat", "worldbank", "oecd", "imf", "ine_es", "ons_uk"}:
                examples = {
                    "eurostat": {
                        "provider": "EUROSTAT",
                        "query": {
                            "dataset_code": "demo_pjan",
                            "filters": {"geo": "PT", "sex": "T", "age": "TOTAL"},
                            "start_period": "2023",
                            "end_period": "2024",
                            "max_observations": 100,
                        },
                    },
                    "worldbank": {
                        "provider": "WORLD_BANK",
                        "query": {
                            "indicator": "SP.POP.TOTL",
                            "countries": ["PRT"],
                            "start_year": 2023,
                            "end_year": 2024,
                            "page_size": 100,
                            "max_pages": 2,
                        },
                    },
                    "oecd": {
                        "provider": "OECD",
                        "query": {
                            "agency": "OECD.SDD.STES",
                            "dataflow": "DSD_STES@DF_CLI",
                            "version": "",
                            "key": ".M.LI...AA...H",
                            "start_period": "2023-02",
                            "end_period": "2023-02",
                            "max_observations": 1000,
                        },
                    },
                    "imf": {
                        "provider": "IMF",
                        "query": {
                            "indicator": "NGDP_RPCH",
                            "economies": ["PRT"],
                            "periods": ["2023", "2024"],
                        },
                    },
                    "ine_es": {
                        "provider": "INE_ES",
                        "query": {"table_id": "50902", "nult": 1, "detail": 2},
                    },
                    "ons_uk": {
                        "provider": "ONS_UK",
                        "query": {
                            "dataset_id": "cpih01",
                            "edition": "time-series",
                            "version": "latest",
                            "dimension_sets": [
                                {
                                    "time": "Oct-11",
                                    "geography": "K02000001",
                                    "aggregate": "cpih1dim1A0",
                                }
                            ],
                        },
                    },
                }
                response = client.post(
                    "/api/internal/statistics/import",
                    json={
                        **examples[source],
                        "legal_basis": (
                            "Operator-authorized validation of official public statistical data"
                        ),
                    },
                )
            elif source == "gleif":
                response = client.post(
                    "/api/v1/relationship-intelligence/ownership/gleif/529900T8BM49AURSDO55"
                )
            elif source == "ted":
                response = client.post(
                    "/api/v1/relationship-intelligence/procurement/ted/search",
                    json={
                        "query": "publication-date >= 20250101 AND notice-type = can-standard",
                        "limit": 3,
                    },
                )
            elif source == "eurlex":
                response = client.post("/api/v1/relationship-intelligence/policy/eurlex/32016R0679")
            else:
                raise SystemExit("Unsupported source: " + source)
            data = response.json()
            if response.status_code != 200:
                report["sources"][source] = {
                    "http_status": response.status_code,
                    "error": data.get("detail"),
                }
                print(source, response.status_code, "FAILED")
                continue
            report["sources"][source] = {
                "http_status": 200,
                "status": data["status"],
                "entities": len(data.get("entity_ids", [])),
                "observations": data.get("observation_count"),
                "relationships": len(data.get("relationship_ids", [])),
                "money_flows": len(data.get("money_flow_ids", [])),
                "demo": data.get("demo", False),
                "source_record_id": data.get("source_record_id"),
                "source_record_ids": data.get("source_record_ids"),
                "artifact_id": data.get("artifact_id"),
                "replayed": data.get("replayed"),
                "warnings": data.get("warnings", []),
            }
            # Real mapped records remain UNVERIFIED until a reviewer checks the source.
            if data.get("relationship_ids"):
                evidence = client.get(
                    "/api/v1/relationships/" + data["relationship_ids"][0] + "/why"
                )
                evidence.raise_for_status()
                edge = evidence.json()["relationship"]
                paths = client.post(
                    "/api/v1/graph/path",
                    json={
                        "source_entity_id": edge["subject_entity_id"],
                        "target_entity_id": edge["object_entity_id"],
                        "verified_only": False,
                    },
                ).json()
                report["sources"][source]["path_count"] = (
                    len(paths.get("paths", [])) if isinstance(paths, dict) else len(paths)
                )
                assert report["sources"][source]["path_count"] > 0, (
                    "Real edge missing from Path Finder"
                )
            print(source, json.dumps(report["sources"][source], ensure_ascii=False))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if any(row["http_status"] != 200 for row in report["sources"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
