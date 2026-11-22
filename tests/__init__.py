import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.index.artifact import IndexArtifact, IndexClaim
from lake.intake.freeze import freeze_day
from lake.intake.station_batch import StationBatch, StationRow
from lake.layout.manifest import SlotAddress
from lake.layout.repack import repack_day
from lake.layout.repack_plan import RepackPlan
from lake.query.project_read import read_project
from lake.query.result import ReadStatus
from lake.storage.bootstrap import initialize_lake, open_lake
from lake.storage.volume import VolumeStore


COPPER = (1, "青河桥东", "QH-A", 1, "铜检", 7)
ZINC = (2, "青河桥东", "QH-A", 2, "锌检", 11)


def split_plan() -> RepackPlan:
    return RepackPlan(("old",), (
        (SlotAddress("old", 0), SlotAddress("copper", 1)),
        (SlotAddress("old", 1), SlotAddress("zinc", 0)),
    ))


class LakeCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory(prefix="qinghe-test-"))
        self.path = Path(directory) / "lake.sqlite3"
        self.connection = ExitStack()
        self.addCleanup(self.connection.close)
        self.reopen()
        initialize_lake(self.db)

    def reopen(self) -> None:
        self.connection.close()
        self.db = self.connection.enter_context(open_lake(self.path))

    def freeze(self, rows, *, station="青河桥东", batch_id="QH-A", volume="old"):
        return freeze_day(self.db, StationBatch(station, batch_id, tuple(rows)), volume)

    def pair(self):
        return self.freeze((StationRow(1, "铜检", 7), StationRow(2, "锌检", 11)))

    def split(self, day_id):
        return repack_day(self.db, day_id, split_plan())

    def capture(self, order):
        store = VolumeStore(self.db)
        claims = tuple(IndexClaim(address, store.read_slot(address).project) for address in sorted(order.scope.addresses))
        return IndexArtifact(order.work_id, order.scope.day_id, claims)

    def corrupt_concentration(self, address: SlotAddress, changed: int) -> None:
        payload, = self.db.execute('''
            SELECT payload FROM volume_slots WHERE volume = ? AND slot = ?
        ''', (address.volume, address.slot)).fetchone()
        record = json.loads(payload)
        self.assertNotEqual(record["concentration_hex"], hex(changed))
        record["concentration_hex"] = hex(changed)
        altered = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.db.execute('''
            UPDATE volume_slots SET payload = ? WHERE volume = ? AND slot = ?
        ''', (altered, address.volume, address.slot))

    def assert_read(self, day_id, project, expected, *, status=ReadStatus.COMPLETE, volume=None):
        result = read_project(self.db, day_id, project)
        actual = tuple((row.sequence, row.origin.station, row.origin.batch_id, row.origin.line,
                        row.project, row.concentration) for row in result.rows)
        self.assertEqual((result.status, result.problem_volume, actual), (status, volume, expected))
        return result
