import sqlite3
from collections.abc import Mapping

from lake.index.artifact import IndexArtifact
from lake.layout.manifest import SlotAddress


class EvidenceBook:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS index_evidence (
                day_id INTEGER NOT NULL REFERENCES frozen_days(day_id),
                source_volume TEXT NOT NULL,
                source_slot INTEGER NOT NULL,
                project TEXT NOT NULL,
                work_id INTEGER NOT NULL REFERENCES work_orders(work_id),
                PRIMARY KEY (day_id, source_volume, source_slot)
            )
        ''')

    def accepted_for_day(self, day_id: int) -> dict[SlotAddress, str]:
        records = self.db.execute('''
            SELECT source_volume, source_slot, project FROM index_evidence
            WHERE day_id = ? ORDER BY source_volume, source_slot
        ''', (day_id,))
        return {SlotAddress(volume, slot): project for volume, slot, project in records}

    def record_claims(self, artifact: IndexArtifact, claims: Mapping[SlotAddress, str]) -> int:
        self.db.executemany('''
            INSERT INTO index_evidence (day_id, source_volume, source_slot, project, work_id)
            VALUES (?, ?, ?, ?, ?)
        ''', ((artifact.day_id, address.volume, address.slot, project, artifact.work_id)
              for address, project in sorted(claims.items())))
        return len(claims)
