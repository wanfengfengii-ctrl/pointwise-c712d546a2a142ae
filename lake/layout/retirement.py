import sqlite3
from collections.abc import Iterable

from lake.intake.origin import require_name
from lake.layout.catalog import LayoutCatalog
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


def retire_volumes(db: sqlite3.Connection, volumes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(volumes, (str, bytes)):
        raise ValueError("provide an iterable of volume names")
    requested = tuple(dict.fromkeys(require_name(volume, "volume") for volume in volumes))
    retired = []
    with transaction(db, write=True):
        catalog = LayoutCatalog(db)
        store = VolumeStore(db)
        for volume in requested:
            state = catalog.replacement_status(volume)
            if state is None or state == "retired" or catalog.references_current(volume):
                continue
            # Registered volumes lose their current reference only by replacement.
            store.release_volume(volume)
            catalog.mark_retired(volume)
            retired.append(volume)
    return tuple(retired)
