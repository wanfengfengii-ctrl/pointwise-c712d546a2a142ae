from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lake.intake.origin import StationOrigin
from lake.intake.reading import Observation


class ReadStatus(str, Enum):
    COMPLETE = "complete"
    PENDING = "pending"
    INTEGRITY_ERROR = "integrity_error"


@dataclass(frozen=True)
class ProjectReading:
    sequence: int
    origin: StationOrigin
    project: str
    concentration: int | None


@dataclass(frozen=True)
class ProjectResult:
    status: ReadStatus
    rows: tuple[ProjectReading, ...] = ()
    problem_volume: str | None = None

    def __post_init__(self) -> None:
        if self.status != ReadStatus.COMPLETE and self.rows:
            raise ValueError("a failed project read cannot expose partial rows")


def assemble_project_result(observations: Iterable[Observation], project: str) -> ProjectResult:
    matching = sorted((row for row in observations if row.project == project), key=lambda row: row.sequence)
    rows = tuple(ProjectReading(row.sequence, row.origin, row.project, row.concentration) for row in matching)
    return ProjectResult(ReadStatus.COMPLETE, rows)
