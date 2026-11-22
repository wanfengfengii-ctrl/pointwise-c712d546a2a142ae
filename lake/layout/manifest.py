from collections.abc import Iterable
from dataclasses import dataclass

from lake.intake.origin import require_name


@dataclass(frozen=True, order=True)
class SlotAddress:
    volume: str
    slot: int

    def __post_init__(self) -> None:
        require_name(self.volume, "volume")
        if type(self.slot) is not int or not 0 <= self.slot <= 2**63 - 1:
            raise ValueError("slot must be a nonnegative 64-bit integer")


@dataclass(frozen=True)
class LayoutManifest:
    day_id: int
    revision: int
    slots: tuple[SlotAddress, ...]

    @property
    def volumes(self) -> tuple[str, ...]:
        return tuple(sorted({address.volume for address in self.slots}))

    def slots_for(self, volume: str) -> tuple[int, ...]:
        return tuple(address.slot for address in self.slots if address.volume == volume)


def validate_manifest(manifest: LayoutManifest, expected_rows: int) -> LayoutManifest:
    if type(manifest.day_id) is not int or manifest.day_id < 1:
        raise ValueError("invalid manifest day")
    if type(manifest.revision) is not int or manifest.revision < 1:
        raise ValueError("invalid manifest revision")
    slots = tuple(manifest.slots)
    if not all(isinstance(address, SlotAddress) for address in slots):
        raise ValueError("layout members must be full slot addresses")
    if len(slots) != expected_rows or len(set(slots)) != expected_rows:
        raise ValueError("layout must contain one distinct slot per frozen observation")
    return LayoutManifest(manifest.day_id, manifest.revision, tuple(sorted(slots)))


def validate_volume_selection(manifest: LayoutManifest, volumes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(volumes, (str, bytes)):
        raise ValueError("provide an iterable of volume names")
    selected = tuple(require_name(volume, "selected volume") for volume in volumes)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("select at least one volume and list each selected volume once")
    missing = set(selected).difference(manifest.volumes)
    if missing:
        raise ValueError(f"volumes outside current layout: {sorted(missing)!r}")
    return selected
