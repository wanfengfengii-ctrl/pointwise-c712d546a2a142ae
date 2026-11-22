from dataclasses import dataclass

from lake.intake.origin import StationOrigin, require_name


def validate_concentration(value: object) -> int | None:
    if value is not None and type(value) is not int:
        raise ValueError("concentration must be an integer in µg/L or null")
    return value


@dataclass(frozen=True)
class Observation:
    sequence: int
    origin: StationOrigin
    project: str
    concentration: int | None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("frozen sequence must be a positive integer")
        if not isinstance(self.origin, StationOrigin):
            raise ValueError("a station origin is required")
        require_name(self.project, "project")
        validate_concentration(self.concentration)
