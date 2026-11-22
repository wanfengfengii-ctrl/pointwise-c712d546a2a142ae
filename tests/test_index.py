from lake.index.artifact import IndexArtifact, IndexClaim
from lake.index.evidence import EvidenceBook
from lake.index.receipt import register_index
from lake.index.work_order import WorkOrderBook, issue_work
from lake.intake.station_batch import StationRow
from lake.layout.manifest import SlotAddress
from lake.query.result import ReadStatus
from lake.storage.readability import ReadabilityStore
from tests import COPPER, LakeCase


class IndexTests(LakeCase):
    def test_v5_rejects_out_of_scope_slot_as_one_artifact(self):
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        ReadabilityStore(self.db).set_readable("old", False)
        self.assert_read(day.day_id, "铅检", (), status=ReadStatus.PENDING, volume="old")
        document = {"work_id": order.work_id, "day_id": day.day_id, "claims": [
            {"volume": "old", "slot": 0, "project": "铜检"},
            {"volume": "old", "slot": 1, "project": "锌检"},
            {"volume": "old", "slot": 9, "project": "铅检"},
        ]}
        with self.assertRaisesRegex(ValueError, "signed work scope"):
            register_index(self.db, document)
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), {})
        self.assert_read(day.day_id, "铅检", (), status=ReadStatus.PENDING, volume="old")

    def test_v5_scope_atomic_keeps_only_previously_accepted_copper(self):
        day = self.pair()
        self.split(day.day_id)
        order = issue_work(self.db, day.day_id, ("copper",))
        copper = IndexClaim(SlotAddress("copper", 1), "铜检")
        unrelated = IndexClaim(SlotAddress("zinc", 0), "锌检")
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, (copper,))), 1)
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")
        with self.assertRaisesRegex(ValueError, "signed work scope"):
            register_index(self.db, IndexArtifact(order.work_id, day.day_id, (copper, unrelated)))
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), {copper.address: "铜检"})
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")

    def test_v5_wrong_day_leaves_original_coverage(self):
        day = self.pair()
        other = self.freeze((StationRow(1, "铜检", 16),), batch_id="QH-B", volume="other")
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.assertEqual(register_index(self.db, artifact), 2)
        before = EvidenceBook(self.db).accepted_for_day(day.day_id)
        with self.assertRaisesRegex(ValueError, "frozen day"):
            register_index(self.db, IndexArtifact(order.work_id, other.day_id, artifact.claims))
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(other.day_id), {})
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), before)
        ReadabilityStore(self.db).set_readable("old", False)
        self.assert_read(day.day_id, "铅检", ())

    def test_v5_conflict_keeps_original_proof_usable(self):
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.assertEqual(register_index(self.db, artifact), 2)
        self.assertEqual(register_index(self.db, artifact), 0)
        conflict = IndexClaim(SlotAddress("old", 0), "锌检")
        with self.assertRaisesRegex(ValueError, "conflicting projects"):
            register_index(self.db, IndexArtifact(order.work_id, day.day_id, (conflict,)))
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), {
            SlotAddress("old", 0): "铜检", SlotAddress("old", 1): "锌检",
        })
        self.assert_read(day.day_id, "铜检", (COPPER,))
        ReadabilityStore(self.db).set_readable("old", False)
        self.assert_read(day.day_id, "铅检", ())
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="old")

    def test_v5_invalid_issue_creates_no_work_order(self):
        day = self.pair()
        self.freeze((StationRow(1, "锌检", 11),), batch_id="QH-Z", volume="foreign")
        with self.assertRaises(KeyError):
            issue_work(self.db, 99, ("old",))
        with self.assertRaisesRegex(ValueError, "outside current layout"):
            issue_work(self.db, day.day_id, ("foreign",))
        with self.assertRaises(KeyError):
            WorkOrderBook(self.db).get(1)
        self.assertEqual(self.db.execute("SELECT work_id FROM work_orders").fetchall(), [])

    def test_first_receipt_must_agree_with_the_signed_observation(self):
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        valid = IndexClaim(SlotAddress("old", 0), "铜检")
        mismatch = IndexClaim(SlotAddress("old", 1), "铜检")
        with self.assertRaisesRegex(ValueError, "differs from the signed source"):
            register_index(self.db, IndexArtifact(order.work_id, day.day_id, (valid, mismatch)))
        self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), {})
