import hashlib
import json
from datetime import datetime
from uuid import UUID


def semantic_key(
    subject_entity_id: UUID,
    relationship_type: str,
    object_entity_id: UUID,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> str:
    payload = {
        "subject": str(subject_entity_id),
        "type": relationship_type,
        "object": str(object_entity_id),
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()
