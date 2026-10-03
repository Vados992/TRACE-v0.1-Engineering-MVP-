import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from app.main import app

target = Path(__file__).resolve().parents[1] / "openapi" / "trace-pia.json"
schema = app.openapi()
for path, operations in schema["paths"].items():
    if path.startswith("/api/v1/"):
        for operation in operations.values():
            if isinstance(operation, dict) and "responses" in operation:
                operation["security"] = [{"HTTPBearer": []}]
target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Exported {len(schema['paths'])} paths")
