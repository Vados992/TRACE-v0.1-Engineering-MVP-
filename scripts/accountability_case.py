"""Offline reproducibility entrypoint: PYTHONPATH=services/api python scripts/accountability_case.py fixture.json"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from app.account_engine import ProjectAssessmentInput, assess  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/accountability_case.py <json>")
    data = ProjectAssessmentInput.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(assess(data).model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
