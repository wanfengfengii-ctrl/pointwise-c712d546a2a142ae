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


def descendant_volumes(volume: str, transfers: Mapping[str, set[str]]) -> set[str]:
    seen = {volume}
    pending = [volume]
    while pending:
        source = pending.pop()
        for target in transfers.get(source, ()):
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return seen


def classify_coverage(
    manifest: LayoutManifest, accepted: Mapping[SlotAddress, str],
    transfers: Mapping[str, set[str]], project: str,
) -> dict[str, Coverage]:
    current = set(manifest.slots)
    projected = defaultdict(set)
    for source, proved_project in accepted.items():
        if source in current:
            continue
        for volume in descendant_volumes(source.volume, transfers):
            address = SlotAddress(volume, source.slot)
            if address in current:
                projected[address].add(proved_project)

    groups = {volume: ([], [], []) for volume in manifest.volumes}
    for address in manifest.slots:
        matches, other, unknown = groups[address.volume]
        proved_project = accepted.get(address)
        hints = projected.get(address, ())
        if proved_project is None and len(hints) == 1:
            proved_project = next(iter(hints))
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
