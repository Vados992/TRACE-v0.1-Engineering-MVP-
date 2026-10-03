import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
load_dotenv(ROOT / ".env")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("TRACE_HOST", "127.0.0.1"),
        port=int(os.getenv("TRACE_PORT", "8000")),
        loop="app.loop:selector_loop" if sys.platform == "win32" else "auto",
    )
