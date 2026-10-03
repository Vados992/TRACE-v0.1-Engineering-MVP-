"""Create private production configuration and independent operator credentials once."""

import hashlib
import json
import os
import secrets
from pathlib import Path


def main():
    path, token_path = Path(".env.production"), Path(".production-keys.json")
    if path.exists() or token_path.exists():
        raise SystemExit(
            "Configuration exists; rotate credentials deliberately, without overwriting files."
        )
    tokens = {
        role: secrets.token_urlsafe(48) for role in ["analyst", "reviewer", "publisher", "admin"]
    }
    mapping = {
        hashlib.sha256(token.encode()).hexdigest(): {"subject": "operator-" + role, "role": role}
        for role, token in tokens.items()
    }
    content = "\n".join(
        [
            "TRACE_ENV=production",
            "TRACE_PORT=8000",
            "PUBLIC_PORT=8080",
            "POSTGRES_PASSWORD=" + secrets.token_urlsafe(36),
            "TRACE_RUNTIME_PASSWORD=" + secrets.token_urlsafe(36),
            "AUTH_KEYS_JSON='" + json.dumps(mapping, separators=(",", ":")) + "'",
            'ALLOWED_HOSTS=["localhost","127.0.0.1","api"]',
            "EVIDENCE_BACKEND=filesystem",
            "",
        ]
    )
    for target, value in [(path, content), (token_path, json.dumps(tokens, indent=2))]:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
    print(
        "Created .env.production and .production-keys.json. Give roles to separate people; protect these files."
    )


if __name__ == "__main__":
    main()
