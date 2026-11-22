from lake.layout.catalog import LayoutCatalog
from lake.layout.manifest import SlotAddress
from lake.layout.repack import repack_day
from lake.layout.repack_plan import RepackPlan
from lake.layout.retirement import retire_volumes
from lake.query.project_read import read_project
from lake.query.result import ReadStatus
from lake.storage.bootstrap import open_lake
from lake.storage.integrity import RecordIntegrityError
from lake.storage.readability import ReadabilityStore, VolumeUnavailable
from lake.storage.volume import VolumeStore
from tests import COPPER, ZINC, LakeCase, split_plan


class RepackTests(LakeCase):
    def test_v3_repartitions_two_volumes_and_retires_both(self):
        day = self.pair()
        self.split(day.day_id)
        self.assertEqual(retire_volumes(self.db, ("old",)), ("old",))
        plan = RepackPlan(("copper", "zinc"), (
            (SlotAddress("zinc", 0), SlotAddress("alpha", 4)),
            (SlotAddress("copper", 1), SlotAddress("beta", 0)),
        ))
        successor = repack_day(self.db, day.day_id, plan)
        self.assertEqual(successor.slots, (SlotAddress("alpha", 4), SlotAddress("beta", 0)))
        self.assertEqual(retire_volumes(self.db, ("copper", "zinc")), ("copper", "zinc"))
        self.reopen()
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id), successor)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_v3_volume_slot_scope_with_equal_local_source_slots(self):
        day = self.pair()
        repack_day(self.db, day.day_id, RepackPlan(("old",), (
            (SlotAddress("old", 0), SlotAddress("left", 0)),
            (SlotAddress("old", 1), SlotAddress("right", 0)),
        )))
        successor = repack_day(self.db, day.day_id, RepackPlan(("left", "right"), (
            (SlotAddress("right", 0), SlotAddress("new-left", 3)),
            (SlotAddress("left", 0), SlotAddress("new-right", 3)),
        )))
        self.assertEqual(successor.slots, (SlotAddress("new-left", 3), SlotAddress("new-right", 3)))
        self.reopen()
        store = VolumeStore(self.db)
        self.assertEqual(store.read_slot(SlotAddress("new-left", 3)).origin.line, 2)
        self.assertEqual(store.read_slot(SlotAddress("new-right", 3)).origin.line, 1)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_v3_conservation_rejects_repeated_source_and_target(self):
        day = self.pair()
        before = LayoutCatalog(self.db).current(day.day_id)
        old_copper, old_zinc = SlotAddress("old", 0), SlotAddress("old", 1)
        target, spare = SlotAddress("new", 1), SlotAddress("new", 2)
        for moves in (((old_copper, target), (old_copper, spare)),
                      ((old_copper, target), (old_zinc, target)),
                      ((old_copper, target),)):
            with self.subTest(moves=moves), self.assertRaises(ValueError):
                repack_day(self.db, day.day_id, RepackPlan(("old",), moves))
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id), before)
        self.assertIsNone(LayoutCatalog(self.db).replacement_status("new"))
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_v3_live_retirement_guard(self):
        day = self.pair()
        after = self.split(day.day_id)
        self.assertEqual(retire_volumes(self.db, ("old",)), ("old",))
        self.assertEqual(retire_volumes(self.db, ("old", "copper", "zinc")), ())
        self.reopen()
        catalog = LayoutCatalog(self.db)
        self.assertEqual(catalog.current(day.day_id), after)
        self.assertEqual(catalog.replacement_status("old"), "retired")
        self.assertEqual(catalog.replacement_status("copper"), "current")
        with self.assertRaises(KeyError):
            ReadabilityStore(self.db).set_readable("old", True)
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_v3_bad_source_keeps_catalog(self):
        day = self.pair()
        before = LayoutCatalog(self.db).current(day.day_id)
        self.corrupt_concentration(SlotAddress("old", 0), 8)
        with self.assertRaises(RecordIntegrityError):
            self.split(day.day_id)
        self.reopen()
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id), before)
        self.assertIsNone(LayoutCatalog(self.db).replacement_status("copper"))
        self.assert_read(day.day_id, "铜检", (), status=ReadStatus.INTEGRITY_ERROR, volume="old")

    def test_v4_abort_before_commit_reader_observes_old_layout(self):
        day = self.pair()
        original = LayoutCatalog(self.db).current(day.day_id)

        def abort():
            with open_lake(self.path) as reader:
                self.assertEqual(LayoutCatalog(reader).current(day.day_id), original)
                visible = read_project(reader, day.day_id, "铜检")
                self.assertEqual(visible.status, ReadStatus.COMPLETE)
                self.assertEqual([(row.origin.batch_id, row.origin.line, row.concentration) for row in visible.rows],
                                 [("QH-A", 1, 7)])
            raise RuntimeError("maintenance aborted")

        with self.assertRaisesRegex(RuntimeError, "maintenance aborted"):
            repack_day(self.db, day.day_id, split_plan(), before_commit=abort)
        self.reopen()
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id), original)
        self.assert_read(day.day_id, "铜检", (COPPER,))

    def test_v4_abort_catalog_rolls_back_targets_and_moves(self):
        day = self.pair()

        def abort_after_writes():
            self.assertEqual(LayoutCatalog(self.db).current(day.day_id).volumes, ("copper", "zinc"))
            self.assertEqual(VolumeStore(self.db).read_slot(SlotAddress("copper", 1)).concentration, 7)
            raise RuntimeError("cancel catalog commit")

        with self.assertRaisesRegex(RuntimeError, "cancel catalog commit"):
            repack_day(self.db, day.day_id, split_plan(), before_commit=abort_after_writes)
        self.reopen()
        catalog = LayoutCatalog(self.db)
        self.assertEqual(catalog.current(day.day_id).volumes, ("old",))
        self.assertEqual(catalog.moves_for_day(day.day_id), {})
        self.assertEqual(catalog.replacement_status("old"), "current")
        self.assertIsNone(catalog.replacement_status("copper"))
        self.assertEqual(self.db.execute("SELECT volume FROM volume_access ORDER BY volume").fetchall(), [("old",)])
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))
        self.assertEqual(self.split(day.day_id).revision, 2)

    def test_unselected_volume_is_preserved_when_selected_source_is_replaced(self):
        day = self.pair()
        self.split(day.day_id)
        plan = RepackPlan(("copper",), ((SlotAddress("copper", 1), SlotAddress("new-copper", 8)),))
        successor = repack_day(self.db, day.day_id, plan)
        self.assertEqual(successor.slots, (SlotAddress("new-copper", 8), SlotAddress("zinc", 0)))
        self.assertEqual(retire_volumes(self.db, ("copper", "zinc")), ("copper",))
        self.assert_read(day.day_id, "铜检", (COPPER,))
        self.assert_read(day.day_id, "锌检", (ZINC,))

    def test_offline_source_blocks_repack_before_publication(self):
        day = self.pair()
        before = LayoutCatalog(self.db).current(day.day_id)
        ReadabilityStore(self.db).set_readable("old", False)
        with self.assertRaises(VolumeUnavailable):
            self.split(day.day_id)
        self.assertEqual(LayoutCatalog(self.db).current(day.day_id), before)
        ReadabilityStore(self.db).set_readable("old", True)
        self.assert_read(day.day_id, "铜检", (COPPER,))
