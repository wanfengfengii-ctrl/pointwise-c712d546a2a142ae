from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from lake.layout.manifest import LayoutManifest, SlotAddress


class CoverageIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class Coverage:
    matches: tuple[SlotAddress, ...]
    other: tuple[SlotAddress, ...]
    unknown: tuple[SlotAddress, ...]


def resolve_address(source: SlotAddress, moves: Mapping[SlotAddress, SlotAddress]) -> SlotAddress:
    """Follow recorded repacks so a claim keeps proving its original frozen observation."""
    seen = set()
    address = source
    while address in moves:
        if address in seen:
            raise CoverageIntegrityError(f"cyclic slot moves recorded for {source!r}")
        seen.add(address)
        address = moves[address]
    return address


def classify_coverage(
    manifest: LayoutManifest, accepted: Mapping[SlotAddress, str],
    moves: Mapping[SlotAddress, SlotAddress], project: str,
) -> dict[str, Coverage]:
    current = set(manifest.slots)
    proved: dict[SlotAddress, str] = {}
    for source, proved_project in accepted.items():
        address = resolve_address(source, moves)
        if address not in current:
            # The proven observation is not part of the current layout; it proves nothing here.
            continue
        prior = proved.get(address)
        if prior is not None and prior != proved_project:
            raise CoverageIntegrityError(f"conflicting proofs resolved to {address!r}")
        proved[address] = proved_project

    groups = {volume: ([], [], []) for volume in manifest.volumes}
    for address in manifest.slots:
        matches, other, unknown = groups[address.volume]
        proved_project = proved.get(address)
        if proved_project is None:
            unknown.append(address)
        elif proved_project == project:
            matches.append(address)
        else:
            other.append(address)
    return {
        volume: Coverage(tuple(matches), tuple(other), tuple(unknown))
        for volume, (matches, other, unknown) in groups.items()
    }
