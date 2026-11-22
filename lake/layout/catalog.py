import sqlite3
from collections import Counter
from collections.abc import Iterable

from lake.intake.day_book import DayBook
from lake.layout.manifest import LayoutManifest, SlotAddress, validate_manifest


class LayoutCatalog:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS layout_heads (
                day_id INTEGER PRIMARY KEY REFERENCES frozen_days(day_id),
                revision INTEGER NOT NULL CHECK (revision > 0)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_registry (
                volume TEXT PRIMARY KEY NOT NULL,
                day_id INTEGER NOT NULL REFERENCES frozen_days(day_id),
                state TEXT NOT NULL CHECK (state IN ('current', 'replaced', 'retired'))
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS layout_members (
                day_id INTEGER NOT NULL REFERENCES layout_heads(day_id),
                volume TEXT NOT NULL REFERENCES volume_registry(volume),
                slot INTEGER NOT NULL CHECK (slot >= 0),
                PRIMARY KEY (day_id, volume, slot),
                UNIQUE (volume, slot)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_transfers (
                day_id INTEGER NOT NULL REFERENCES frozen_days(day_id),
                source_volume TEXT NOT NULL REFERENCES volume_registry(volume),
                target_volume TEXT NOT NULL REFERENCES volume_registry(volume),
                row_count INTEGER NOT NULL CHECK (row_count > 0),
                PRIMARY KEY (day_id, source_volume, target_volume)
            )
        ''')

    def current(self, day_id: int) -> LayoutManifest:
        day = DayBook(self.db).get(day_id)
        # Read the revision and its members in a single statement, even for standalone calls.
        records = self.db.execute('''
            SELECT h.revision, m.volume, m.slot
            FROM layout_heads AS h
            LEFT JOIN layout_members AS m ON m.day_id = h.day_id
            WHERE h.day_id = ? ORDER BY m.volume, m.slot
        ''', (day_id,)).fetchall()
        if not records:
            raise KeyError(f"frozen day has no published layout: {day_id}")
        slots = tuple(SlotAddress(volume, slot) for _, volume, slot in records if volume is not None)
        return validate_manifest(LayoutManifest(day_id, records[0][0], slots), day.row_count)

    def require_new_volumes(self, volumes: Iterable[str]) -> None:
        for volume in volumes:
            if self.replacement_status(volume) is not None:
                raise ValueError(f"volume name has already been allocated: {volume!r}")

    def publish(
        self, manifest: LayoutManifest, *, previous: LayoutManifest | None = None,
    ) -> LayoutManifest:
        day = DayBook(self.db).get(manifest.day_id)
        manifest = validate_manifest(manifest, day.row_count)
        if previous is None:
            if manifest.revision != 1:
                raise ValueError("initial layout must have revision 1")
            old_volumes = set()
        else:
            if previous.day_id != day.day_id or self.current(day.day_id) != previous:
                raise ValueError("source manifest is no longer current")
            if manifest.revision != previous.revision + 1:
                raise ValueError("replacement must advance the layout by one revision")
            old_volumes = set(previous.volumes)
            for volume in old_volumes.intersection(manifest.volumes):
                if manifest.slots_for(volume) != previous.slots_for(volume):
                    raise ValueError(f"retained volume slots changed: {volume!r}")

        new_volumes = sorted(set(manifest.volumes).difference(old_volumes))
        removed_volumes = sorted(old_volumes.difference(manifest.volumes))
        self.require_new_volumes(new_volumes)
        self.db.executemany('''
            INSERT INTO volume_registry (volume, day_id, state) VALUES (?, ?, 'current')
        ''', ((volume, day.day_id) for volume in new_volumes))
        if previous is None:
            self.db.execute("INSERT INTO layout_heads VALUES (?, ?)", (day.day_id, manifest.revision))
        else:
            self.db.execute('''
                UPDATE layout_heads SET revision = ? WHERE day_id = ?
            ''', (manifest.revision, day.day_id))
            self.db.execute("DELETE FROM layout_members WHERE day_id = ?", (day.day_id,))
        self.db.executemany('''
            INSERT INTO layout_members (day_id, volume, slot) VALUES (?, ?, ?)
        ''', ((day.day_id, address.volume, address.slot) for address in manifest.slots))
        self.db.executemany('''
            UPDATE volume_registry SET state = 'replaced' WHERE volume = ?
        ''', ((volume,) for volume in removed_volumes))
        return manifest

    def record_moves(self, day_id: int, moves: Iterable[tuple[SlotAddress, SlotAddress]]) -> None:
        counts = Counter((source.volume, target.volume) for source, target in moves)
        self.db.executemany('''
            INSERT INTO volume_transfers (day_id, source_volume, target_volume, row_count)
            VALUES (?, ?, ?, ?)
        ''', ((day_id, source, target, count) for (source, target), count in counts.items()))

    def moves_for_day(self, day_id: int) -> dict[SlotAddress, SlotAddress]:
        legacy = self.db.execute('''
            SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'slot_moves'
        ''').fetchone()
        if legacy is None:
            return {}
        rows = self.db.execute('''
            SELECT source_volume, source_slot, target_volume, target_slot
            FROM slot_moves WHERE day_id = ?
        ''', (day_id,))
        return {
            SlotAddress(source_volume, source_slot): SlotAddress(target_volume, target_slot)
            for source_volume, source_slot, target_volume, target_slot in rows
        }

    def transfers_for_day(self, day_id: int) -> dict[str, set[str]]:
        transfers = {}
        for source, target in self.moves_for_day(day_id).items():
            transfers.setdefault(source.volume, set()).add(target.volume)
        for source, target in self.db.execute('''
            SELECT source_volume, target_volume FROM volume_transfers WHERE day_id = ?
        ''', (day_id,)):
            transfers.setdefault(source, set()).add(target)
        return transfers

    def references_current(self, volume: str) -> bool:
        row = self.db.execute("SELECT 1 FROM layout_members WHERE volume = ? LIMIT 1", (volume,)).fetchone()
        return row is not None

    def replacement_status(self, volume: str) -> str | None:
        row = self.db.execute("SELECT state FROM volume_registry WHERE volume = ?", (volume,)).fetchone()
        return None if row is None else row[0]

    def mark_retired(self, volume: str) -> None:
        self.db.execute("UPDATE volume_registry SET state = 'retired' WHERE volume = ?", (volume,))
