import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lake.index.scope import WorkScope
from lake.layout.catalog import LayoutCatalog
from lake.layout.manifest import SlotAddress
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


@dataclass(frozen=True)
class WorkOrder:
    work_id: int
    scope: WorkScope


class WorkOrderBook:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS work_orders (
                work_id INTEGER PRIMARY KEY,
                day_id INTEGER NOT NULL REFERENCES frozen_days(day_id),
                revision INTEGER NOT NULL CHECK (revision > 0)
            )
        ''')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS work_slots (
                work_id INTEGER NOT NULL REFERENCES work_orders(work_id),
                volume TEXT NOT NULL,
                slot INTEGER NOT NULL,
                project_digest BLOB NOT NULL,
                PRIMARY KEY (work_id, volume, slot)
            )
        ''')

    def register(self, scope: WorkScope, commitments: Mapping[SlotAddress, bytes]) -> WorkOrder:
        if commitments.keys() != scope.addresses:
            raise ValueError("project commitments must cover the exact work scope")
        cursor = self.db.execute('''
            INSERT INTO work_orders (day_id, revision) VALUES (?, ?)
        ''', (scope.day_id, scope.revision))
        work_id = cursor.lastrowid
        self.db.executemany('''
            INSERT INTO work_slots (work_id, volume, slot, project_digest) VALUES (?, ?, ?, ?)
        ''', ((work_id, address.volume, address.slot, commitments[address]) for address in sorted(scope.addresses)))
        return WorkOrder(work_id, scope)

    def get(self, work_id: int) -> WorkOrder:
        if type(work_id) is not int or not 1 <= work_id <= 2**63 - 1:
            raise KeyError(f"unknown work order: {work_id!r}")
        header = self.db.execute('''
            SELECT day_id, revision FROM work_orders WHERE work_id = ?
        ''', (work_id,)).fetchone()
        if header is None:
            raise KeyError(f"unknown work order: {work_id}")
        rows = self.db.execute("SELECT volume, slot FROM work_slots WHERE work_id = ?", (work_id,))
        addresses = frozenset(SlotAddress(volume, slot) for volume, slot in rows)
        return WorkOrder(work_id, WorkScope(header[0], header[1], addresses))

    def project_commitments(self, work_id: int) -> dict[SlotAddress, bytes]:
        records = self.db.execute('''
            SELECT volume, slot, project_digest FROM work_slots WHERE work_id = ?
        ''', (work_id,))
        return {SlotAddress(volume, slot): digest for volume, slot, digest in records}


def issue_work(db: sqlite3.Connection, day_id: int, volumes: Iterable[str]) -> WorkOrder:
    with transaction(db, write=True):
        manifest = LayoutCatalog(db).current(day_id)
        scope = WorkScope.from_manifest(manifest, volumes)
        store = VolumeStore(db)
        commitments = {address: store.get_project_commitment(address) for address in scope.addresses}
        return WorkOrderBook(db).register(scope, commitments)
