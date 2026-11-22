from collections.abc import Iterable
from dataclasses import dataclass

from lake.layout.manifest import LayoutManifest, SlotAddress, validate_volume_selection


@dataclass(frozen=True)
class WorkScope:
    day_id: int
    revision: int
    addresses: frozenset[SlotAddress]

    @property
    def volumes(self) -> tuple[str, ...]:
        return tuple(sorted({address.volume for address in self.addresses}))

    @classmethod
    def from_manifest(cls, manifest: LayoutManifest, volumes: Iterable[str]) -> 'WorkScope':
        selected = set(validate_volume_selection(manifest, volumes))
        addresses = frozenset(address for address in manifest.slots if address.volume in selected)
        return cls(manifest.day_id, manifest.revision, addresses)

    def contains(self, address: SlotAddress) -> bool:
        return address in self.addresses
