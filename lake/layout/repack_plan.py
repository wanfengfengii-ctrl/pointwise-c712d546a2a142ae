from collections.abc import Sequence
from dataclasses import dataclass

from lake.layout.manifest import LayoutManifest, SlotAddress, validate_volume_selection


@dataclass(frozen=True)
class RepackPlan:
    replace: Sequence[str]
    moves: Sequence[tuple[SlotAddress, SlotAddress]]


def validate_repack_plan(manifest: LayoutManifest, request: RepackPlan) -> RepackPlan:
    if not isinstance(request, RepackPlan):
        raise ValueError("a repack plan is required")
    selected = validate_volume_selection(manifest, request.replace)
    selected_volumes = set(selected)
    current_volumes = set(manifest.volumes)
    expected_sources = {address for address in manifest.slots if address.volume in selected_volumes}
    used_sources = set()
    used_targets = set()
    moves = []

    for pair in request.moves:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("each move must contain one source and one target")
        source, target = pair
        if not isinstance(source, SlotAddress) or not isinstance(target, SlotAddress):
            raise ValueError("each move requires two full slot addresses")
        if source not in expected_sources or source in used_sources:
            raise ValueError(f"unselected or repeated source slot: {source!r}")
        if target.volume in current_volumes or target in used_targets:
            raise ValueError(f"target slot is reused or not on a new volume: {target!r}")
        used_sources.add(source)
        used_targets.add(target)
        moves.append((source, target))
    if used_sources != expected_sources:
        raise ValueError(f"repack omitted source slots: {sorted(expected_sources - used_sources)!r}")
    return RepackPlan(selected, tuple(moves))
