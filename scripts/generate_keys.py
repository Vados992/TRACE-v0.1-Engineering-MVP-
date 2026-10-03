"""Generate independent random credentials; run locally, never in CI logs."""

import hashlib
import json
import secrets

if __name__ == "__main__":
    keys = {}
    for role in ["analyst", "reviewer", "publisher", "admin"]:
        token = secrets.token_urlsafe(48)
        print(f"{role}: {token}")
        keys[hashlib.sha256(token.encode()).hexdigest()] = {
            "subject": f"operator-{role}",
            "role": role,
        }
    print("AUTH_KEYS_JSON=" + json.dumps(keys, separators=(",", ":")))
