from lake.index.artifact import IndexArtifact
from lake.index.evidence import EvidenceBook
from lake.index.receipt import register_index
from lake.index.work_order import WorkOrderBook, issue_work
from lake.intake.day_book import DayBook
from lake.intake.station_batch import StationRow
from lake.layout.catalog import LayoutCatalog
from lake.layout.manifest import SlotAddress
from lake.layout.repack import repack_day
from lake.layout.repack_plan import RepackPlan
from lake.layout.retirement import retire_volumes
from lake.query.result import ReadStatus
from lake.storage.bootstrap import initialize_lake
from lake.storage.integrity import RecordIntegrityError
from lake.storage.readability import ReadabilityStore, VolumeUnavailable
from lake.storage.volume import VolumeStore
from tests import COPPER, ZINC, LakeCase


class ProjectReadTests(LakeCase):
    def prepared_late_artifact(self):
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.split(day.day_id)
        self.assertEqual(retire_volumes(self.db, ("old",)), ("old",))
        return day, order, artifact

    def test_v6_accepts_old_artifact_after_volume_release(self):
        day, order, artifact = self.prepared_late_artifact()
        self.reopen()
        self.assertEqual(WorkOrderBook(self.db).get(order.work_id), order)
        with self.assertRaises(RecordIntegrityError):
            VolumeStore(self.db).read_slot(SlotAddress("old", 0))
        self.assertEqual(register_index(self.db, artifact), 2)
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (COPPER,))

    def test_v6_slot_collision_preserves_copper_with_zinc_offline(self):
        day, _, artifact = self.prepared_late_artifact()
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id).slots,
                         (SlotAddress("copper", 1), SlotAddress("zinc", 0)))
        self.assertEqual(register_index(self.db, artifact), 2)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (), status=ReadStatus.PENDING, volume="zinc")

    def test_v7_partial_old_coverage_leaves_unknown_volume_required(self):
        day, order, artifact = self.prepared_late_artifact()
        partial = IndexArtifact(order.work_id, day.day_id, artifact.claims[:1])
        self.assertEqual(register_index(self.db, partial), 1)
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")

    def test_v7_partial_then_complete_survives_reopen(self):
        day, order, artifact = self.prepared_late_artifact()
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[:1])), 1)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[1:])), 1)
        self.reopen()
        with self.assertRaises(VolumeUnavailable):
            VolumeStore(self.db).read_slot(SlotAddress("zinc", 0))
        self.assert_read(day.day_id, "铜检", (COPPER,))

    def test_v7_match_offline_requires_all_equal_copper_occurrences(self):
        day = self.freeze((StationRow(8, "铜检", 7), StationRow(3, "铜检", 7)))
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.split(day.day_id)
        register_index(self.db, artifact)
        self.assert_read(day.day_id, "铜检", (
            (1, "青河桥东", "QH-A", 8, "铜检", 7),
            (2, "青河桥东", "QH-A", 3, "铜检", 7),
        ))
        access = ReadabilityStore(self.db)
        for volume in ("copper", "zinc"):
            with self.subTest(volume=volume):
                access.set_readable(volume, False)
                self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume=volume)
                access.set_readable(volume, True)

    def test_v7_readable_corruption_returns_no_partial_rows(self):
        day = self.freeze((StationRow(2, "铜检", 5), StationRow(4, "铜检", 7)))
        self.split(day.day_id)
        self.assert_read(day.day_id, "铜检", (
            (1, "青河桥东", "QH-A", 2, "铜检", 5),
            (2, "青河桥东", "QH-A", 4, "铜检", 7),
        ))
        self.corrupt_concentration(SlotAddress("zinc", 0), 8)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.INTEGRITY_ERROR, volume="zinc")

    def test_v8_null_result_keeps_origin_and_day_after_initialization(self):
        day = self.freeze((StationRow(6, "铜检", None), StationRow(9, "锌检", 11)), batch_id="QH-M")
        self.split(day.day_id)
        order = issue_work(self.db, day.day_id, ("copper", "zinc"))
        register_index(self.db, self.capture(order))
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.reopen()
        initialize_lake(self.db)
        initialize_lake(self.db)
        self.assertEqual(DayBook(self.db).get(day.day_id), day)
        self.assert_read(day.day_id, "铜检", ((1, "青河桥东", "QH-M", 6, "铜检", None),))
        self.assert_read(day.day_id, "锌检", (), status=ReadStatus.PENDING, volume="zinc")

    def test_v8_zero_and_null_are_both_delivered(self):
        day = self.freeze((StationRow(2, "铜检", 0), StationRow(9, "铜检", None)))
        self.assert_read(day.day_id, "铜检", (
            (1, "青河桥东", "QH-A", 2, "铜检", 0),
            (2, "青河桥东", "QH-A", 9, "铜检", None),
        ))

    def test_v8_reopen_state_preserves_directory_receipts_and_volume_access(self):
        day, order, artifact = self.prepared_late_artifact()
        register_index(self.db, artifact)
        catalog = LayoutCatalog(self.db)
        directory = catalog.current(day.day_id)
        accepted = {SlotAddress("old", 0): "铜检", SlotAddress("old", 1): "锌检"}
        ReadabilityStore(self.db).set_readable("zinc", False)
        for _ in range(2):
            self.reopen()
            initialize_lake(self.db)
            self.assertEqual(LayoutCatalog(self.db).current(day.day_id), directory)
            self.assertEqual(LayoutCatalog(self.db).replacement_status("old"), "retired")
            self.assertEqual(EvidenceBook(self.db).accepted_for_day(day.day_id), accepted)
            self.assertEqual(WorkOrderBook(self.db).get(order.work_id), order)
            self.assert_read(day.day_id, "铜检", (COPPER,))
            self.assert_read(day.day_id, "锌检", (), status=ReadStatus.PENDING, volume="zinc")
        ReadabilityStore(self.db).set_readable("zinc", True)
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_early_and_late_proof_survive_merge_then_split(self):
        day = self.pair()
        self.split(day.day_id)
        order = issue_work(self.db, day.day_id, ("copper", "zinc"))
        artifact = self.capture(order)
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[:1])), 1)
        repack_day(self.db, day.day_id, RepackPlan(("copper", "zinc"), (
            (SlotAddress("zinc", 0), SlotAddress("packed", 8)),
            (SlotAddress("copper", 1), SlotAddress("packed", 13)),
        )))
        self.assertEqual(retire_volumes(self.db, ("old", "copper", "zinc")), ("old", "copper", "zinc"))
        repack_day(self.db, day.day_id, RepackPlan(("packed",), (
            (SlotAddress("packed", 13), SlotAddress("final-copper", 0)),
            (SlotAddress("packed", 8), SlotAddress("final-zinc", 1)),
        )))
        self.assertEqual(retire_volumes(self.db, ("packed",)), ("packed",))
        ReadabilityStore(self.db).set_readable("final-zinc", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="final-zinc")
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[1:])), 1)
        self.reopen()
        self.assert_read(day.day_id, "铜检", (COPPER,))

    def test_partial_evidence_distinguishes_equal_rows(self):
        day = self.freeze((StationRow(1, "锌检", 11), StationRow(2, "锌检", 11)))
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.split(day.day_id)
        retire_volumes(self.db, ("old",))
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[:1])), 1)
        access = ReadabilityStore(self.db)
        access.set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")
        access.set_readable("zinc", True)
        access.set_readable("copper", False)
        self.assert_read(day.day_id, "铜检", ())

    def test_negative_proof_for_one_member_does_not_exclude_its_whole_volume(self):
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[1:]))
        ReadabilityStore(self.db).set_readable("old", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="old")

    def test_claim_follows_recorded_slot_number_change(self):
        # incident: old:0 copper -> copper:1, old:1 zinc -> zinc:0.  A volume-only
        # projection would look for copper at copper:0 and miss it.
        day = self.pair()
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        self.split(day.day_id)
        self.assertEqual(retire_volumes(self.db, ("old",)), ("old",))
        copper_claim, zinc_claim = artifact.claims
        self.assertEqual((copper_claim.address, zinc_claim.address),
                         (SlotAddress("old", 0), SlotAddress("old", 1)))
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, (copper_claim,))), 1)
        ReadabilityStore(self.db).set_readable("zinc", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="zinc")
        self.reopen()
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, (zinc_claim,))), 1)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assertEqual(self.db.execute('''
            SELECT source_volume, source_slot, target_volume, target_slot FROM slot_moves ORDER BY source_slot
        ''').fetchall(), [("old", 0, "copper", 1), ("old", 1, "zinc", 0)])

    def test_reordered_slots_in_one_target_volume_keep_original_observations(self):
        day = self.freeze((StationRow(4, "铜检", 7), StationRow(2, "锌检", 11)))
        order = issue_work(self.db, day.day_id, ("old",))
        artifact = self.capture(order)
        repack_day(self.db, day.day_id, RepackPlan(("old",), (
            (SlotAddress("old", 0), SlotAddress("packed", 9)),
            (SlotAddress("old", 1), SlotAddress("packed", 2)),
        )))
        self.assertEqual(retire_volumes(self.db, ("old",)), ("old",))
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id).slots,
                         (SlotAddress("packed", 2), SlotAddress("packed", 9)))
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[:1])), 1)
        ReadabilityStore(self.db).set_readable("packed", False)
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.PENDING, volume="packed")
        self.assertEqual(register_index(self.db, IndexArtifact(order.work_id, day.day_id, artifact.claims[1:])), 1)
        ReadabilityStore(self.db).set_readable("packed", True)
        self.assert_read(day.day_id, "铜检", (
            (1, "青河桥东", "QH-A", 4, "铜检", 7),
        ))
        self.assert_read(day.day_id, "锌检", (
            (2, "青河桥东", "QH-A", 2, "锌检", 11),
        ))
