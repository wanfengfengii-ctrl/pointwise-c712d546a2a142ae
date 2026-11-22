import sqlite3
from collections.abc import Callable

from lake.layout.catalog import LayoutCatalog
from lake.layout.manifest import LayoutManifest
from lake.layout.repack_plan import RepackPlan, validate_repack_plan
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


def repack_day(
    db: sqlite3.Connection, day_id: int, plan: RepackPlan, *, before_commit: Callable[[], None] | None = None,
) -> LayoutManifest:
    with transaction(db, write=True):
        catalog = LayoutCatalog(db)
        store = VolumeStore(db)
        previous = catalog.current(day_id)
        plan = validate_repack_plan(previous, plan)
        target_volumes = sorted({target.volume for _, target in plan.moves})
        catalog.require_new_volumes(target_volumes)

        source_rows = {}
        for volume in plan.replace:
            source_rows.update(store.read_volume(volume, previous.slots_for(volume)))
        by_volume = {volume: {} for volume in target_volumes}
        for source, target in plan.moves:
            by_volume[target.volume][target.slot] = source_rows[source]
        for volume, rows in by_volume.items():
            store.write_volume(volume, rows)

        selected = set(plan.replace)
        kept = tuple(address for address in previous.slots if address.volume not in selected)
        targets = tuple(target for _, target in plan.moves)
        replacement = LayoutManifest(day_id, previous.revision + 1, kept + targets)
        published = catalog.publish(replacement, previous=previous)
        catalog.record_moves(day_id, plan.moves)
        if before_commit is not None:
            before_commit()
    return published
