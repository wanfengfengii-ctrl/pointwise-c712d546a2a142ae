from dataclasses import dataclass


def require_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or not value.isprintable():
        raise ValueError(f"{label} must be a nonempty printable name without surrounding whitespace")
    return value


@dataclass(frozen=True)
class StationOrigin:
    station: str
    batch_id: str
    line: int

    def __post_init__(self) -> None:
        require_name(self.station, "station")
        require_name(self.batch_id, "station batch")
        if type(self.line) is not int or not 1 <= self.line <= 2**63 - 1:
            raise ValueError("station line must be a positive 64-bit integer")
