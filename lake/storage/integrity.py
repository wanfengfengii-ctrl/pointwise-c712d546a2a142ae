import hashlib
import hmac
import json

from lake.layout.manifest import SlotAddress


class RecordIntegrityError(ValueError):
    pass


def record_digest(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def verify_record(payload: bytes, expected: bytes) -> None:
    if not isinstance(payload, bytes) or not isinstance(expected, bytes):
        raise RecordIntegrityError("record payload and digest must be bytes")
    if not hmac.compare_digest(record_digest(payload), expected):
        raise RecordIntegrityError("record digest mismatch")


def project_commitment(address: SlotAddress, project: str) -> bytes:
    identity = json.dumps([address.volume, address.slot, project], separators=(",", ":"))
    return record_digest(identity.encode("ascii"))
