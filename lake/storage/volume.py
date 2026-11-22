import sqlite3
from collections.abc import Mapping, Sequence

from lake.intake.reading import Observation
from lake.layout.manifest import SlotAddress
from lake.storage.integrity import RecordIntegrityError, project_commitment, record_digest, verify_record
from lake.storage.readability import ReadabilityStore
from lake.storage.row_codec import RowDecodeError, decode_observation, encode_observation


class VolumeStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.access = ReadabilityStore(db)

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_slots (
                volume TEXT NOT NULL REFERENCES volume_access(volume) ON DELETE CASCADE,
                slot INTEGER NOT NULL CHECK (slot >= 0),
                payload BLOB NOT NULL,
                digest BLOB NOT NULL,
                project_digest BLOB NOT NULL,
                PRIMARY KEY (volume, slot)
            )
        ''')

    def write_volume(self, volume: str, rows: Mapping[int, Observation]) -> None:
        if not rows:
            raise ValueError("a volume must contain at least one observation")
        records = []
        for slot, row in rows.items():
            address = SlotAddress(volume, slot)
            payload = encode_observation(row)
            records.append((volume, slot, payload, record_digest(payload), project_commitment(address, row.project)))
        self.access.register(volume)
        self.db.executemany('''
            INSERT INTO volume_slots (volume, slot, payload, digest, project_digest)
            VALUES (?, ?, ?, ?, ?)
        ''', records)

    def _decode(self, address: SlotAddress, payload: bytes, digest: bytes) -> Observation:
        try:
            verify_record(payload, digest)
            return decode_observation(payload)
        except (RecordIntegrityError, RowDecodeError) as exc:
            raise RecordIntegrityError(f"invalid record at {address.volume!r} slot {address.slot}") from exc

    def read_slot(self, address: SlotAddress) -> Observation:
        self.access.require_readable(address.volume)
        record = self.db.execute('''
            SELECT payload, digest FROM volume_slots WHERE volume = ? AND slot = ?
        ''', (address.volume, address.slot)).fetchone()
        if record is None:
            raise RecordIntegrityError(f"missing record at {address.volume!r} slot {address.slot}")
        return self._decode(address, *record)

    def read_volume(self, volume: str, expected_slots: Sequence[int]) -> dict[SlotAddress, Observation]:
        self.access.require_readable(volume)
        records = self.db.execute('''
            SELECT slot, payload, digest FROM volume_slots WHERE volume = ? ORDER BY slot
        ''', (volume,)).fetchall()
        if tuple(record[0] for record in records) != tuple(sorted(expected_slots)):
            raise RecordIntegrityError(f"stored slots differ from the layout for {volume!r}")
        observations = {}
        for slot, payload, digest in records:
            address = SlotAddress(volume, slot)
            observations[address] = self._decode(address, payload, digest)
        return observations

    def get_project_commitment(self, address: SlotAddress) -> bytes:
        record = self.db.execute('''
            SELECT project_digest FROM volume_slots WHERE volume = ? AND slot = ?
        ''', (address.volume, address.slot)).fetchone()
        if record is None:
            raise RecordIntegrityError(f"missing index source slot: {address!r}")
        return record[0]

    def release_volume(self, volume: str) -> None:
        self.access.release(volume)
