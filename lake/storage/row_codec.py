import json

from lake.intake.origin import StationOrigin
from lake.intake.reading import Observation


class RowDecodeError(ValueError):
    pass


def encode_observation(row: Observation) -> bytes:
    # Hex keeps exact integers independent of the interpreter's decimal digit limit.
    concentration = None if row.concentration is None else hex(row.concentration)
    return json.dumps({
        "sequence": row.sequence,
        "station": row.origin.station,
        "batch_id": row.origin.batch_id,
        "line": row.origin.line,
        "project": row.project,
        "concentration_hex": concentration,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_observation(payload: bytes) -> Observation:
    try:
        record = json.loads(payload.decode("utf-8"))
        if not isinstance(record, dict) or record.keys() != {
            "sequence", "station", "batch_id", "line", "project", "concentration_hex",
        }:
            raise ValueError("unexpected observation fields")
        token = record["concentration_hex"]
        concentration = None
        if token is not None:
            if not isinstance(token, str):
                raise ValueError("invalid concentration representation")
            concentration = int(token, 16)
            if hex(concentration) != token:
                raise ValueError("noncanonical concentration representation")
        origin = StationOrigin(record["station"], record["batch_id"], record["line"])
        return Observation(record["sequence"], origin, record["project"], concentration)
    except (ValueError, TypeError, RecursionError) as exc:
        raise RowDecodeError("invalid frozen observation record") from exc
