import hashlib
import json

MAX_JSON_BYTES = 16 * 1024 * 1024

def canonical_bytes(value: dict) -> bytes:
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > MAX_JSON_BYTES:
        raise ValueError('JSON_SIZE_EXCEEDED')
    return data

def sha256_json(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
