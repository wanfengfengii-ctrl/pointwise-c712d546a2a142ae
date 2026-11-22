from collections.abc import Sequence
from dataclasses import dataclass

from lake.intake.origin import StationOrigin, require_name
from lake.intake.reading import validate_concentration


@dataclass(frozen=True)
class StationRow:
    line: int
    project: str
    concentration: int | None


@dataclass(frozen=True)
class StationBatch:
    station: str
    batch_id: str
    rows: Sequence[StationRow]


def validate_station_batch(batch: StationBatch) -> tuple[StationRow, ...]:
    if not isinstance(batch, StationBatch):
        raise ValueError("a station batch is required")
    require_name(batch.station, "station")
    require_name(batch.batch_id, "station batch")
    if not isinstance(batch.rows, Sequence) or isinstance(batch.rows, (str, bytes)):
        raise ValueError("station rows must be an ordered sequence")
    rows = tuple(batch.rows)
    if not rows:
        raise ValueError("a station batch must contain at least one row")

    seen_lines = set()
    for row in rows:
        if not isinstance(row, StationRow):
            raise ValueError("each station row must be a StationRow")
        StationOrigin(batch.station, batch.batch_id, row.line)
        if row.line in seen_lines:
            raise ValueError(f"station line appears more than once: {row.line}")
        seen_lines.add(row.line)
        require_name(row.project, "project")
        validate_concentration(row.concentration)
    return rows
