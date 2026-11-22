from lake.intake.day_book import DayBook
from lake.intake.station_batch import StationRow
from lake.layout.catalog import LayoutCatalog
from tests import LakeCase


class FreezeTests(LakeCase):
    def test_v1_equal_values_remain_distinct_in_input_order(self):
        day = self.freeze((StationRow(9, "铜检", 7), StationRow(2, "铜检", 7)))
        self.assertEqual(day.row_count, 2)
        self.assertEqual(DayBook(self.db).get(day.day_id), day)
        self.assert_read(day.day_id, "铜检", (
            (1, "青河桥东", "QH-A", 9, "铜检", 7),
            (2, "青河桥东", "QH-A", 2, "铜检", 7),
        ))

    def test_v2_rejects_concentration_string_before_registration(self):
        with self.assertRaisesRegex(ValueError, "concentration"):
            self.freeze((StationRow(1, "铜检", "7"),))
        self.assertEqual(self.db.execute("SELECT day_id FROM frozen_days").fetchall(), [])
        self.assertIsNone(LayoutCatalog(self.db).replacement_status("old"))

    def test_v2_invalid_after_valid_does_not_publish_prefix(self):
        with self.assertRaisesRegex(ValueError, "concentration"):
            self.freeze((StationRow(4, "锌检", 11), StationRow(9, "铜检", "7")))
        self.reopen()
        with self.assertRaises(KeyError):
            DayBook(self.db).get(1)
        self.assertEqual(self.db.execute("SELECT volume FROM volume_access").fetchall(), [])
        day = self.pair()
        self.assertEqual(day.row_count, 2)

    def test_invalid_station_rows_leave_no_day(self):
        for rows in (
            (),
            (StationRow(1, "铜检", True),),
            (StationRow(1, "铜检", 7), StationRow(1, "锌检", 11)),
            (StationRow(0, "铜检", 7),),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.freeze(rows)
        self.assertEqual(self.db.execute("SELECT day_id FROM frozen_days").fetchall(), [])

    def test_duplicate_station_batch_keeps_the_original_day(self):
        first = self.pair()
        with self.assertRaisesRegex(ValueError, "already frozen"):
            self.freeze((StationRow(1, "铜检", 20),), volume="other")
        self.assertEqual(DayBook(self.db).get(first.day_id), first)
        self.assertIsNone(LayoutCatalog(self.db).replacement_status("other"))
        self.assert_read(first.day_id, "铜检", ((1, "青河桥东", "QH-A", 1, "铜检", 7),))
