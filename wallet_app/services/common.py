import hashlib
import json
import uuid

def request_fingerprint(operation, wallet_ids, amount_minor, extra=None):
    payload = {
        "operation": operation,
        "wallet_ids": list(wallet_ids),
        "amount_minor": int(amount_minor),
        "extra": extra or {},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

def new_idempotency_key():
    return str(uuid.uuid4())

def row_dict(row):
    return dict(row) if row is not None else None

def replay_or_conflict(tx_repo, conn, key, fingerprint):
    previous = tx_repo.get_by_key(conn, key)
    if previous is None:
        return None
    if previous["request_hash"] != fingerprint:
        return {"conflict": True}
    return {"conflict": False, "transaction": dict(previous)}
