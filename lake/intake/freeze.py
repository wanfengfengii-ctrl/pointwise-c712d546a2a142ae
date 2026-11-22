import sqlite3

from lake.intake.day_book import DayBook, FrozenDay
from lake.intake.origin import StationOrigin, require_name
from lake.intake.reading import Observation
from lake.intake.station_batch import StationBatch, validate_station_batch
from lake.layout.catalog import LayoutCatalog
from lake.layout.manifest import LayoutManifest, SlotAddress
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


def freeze_day(db: sqlite3.Connection, batch: StationBatch, initial_volume: str) -> FrozenDay:
    rows = validate_station_batch(batch)
    require_name(initial_volume, "initial volume")
    observations = {}
    for slot, row in enumerate(rows):
        origin = StationOrigin(batch.station, batch.batch_id, row.line)
        observations[slot] = Observation(slot + 1, origin, row.project, row.concentration)
    addresses = tuple(SlotAddress(initial_volume, slot) for slot in observations)

    with transaction(db, write=True):
        catalog = LayoutCatalog(db)
        catalog.require_new_volumes((initial_volume,))
        day = DayBook(db).register(batch.station, batch.batch_id, len(observations))
        VolumeStore(db).write_volume(initial_volume, observations)
        catalog.publish(LayoutManifest(day.day_id, 1, addresses))
    return day
