import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lake.index.evidence import EvidenceBook
from lake.index.work_order import WorkOrderBook
from lake.intake.day_book import DayBook
from lake.layout.catalog import LayoutCatalog
from lake.storage.readability import ReadabilityStore
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


@contextmanager
def open_lake(path: str | Path) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        yield db
    finally:
        db.close()


def initialize_lake(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise RuntimeError("lake initialization requires an idle connection")
    # Readers can keep their existing layout snapshot while a replacement is staged.
    db.execute("PRAGMA journal_mode = WAL").fetchone()
    with transaction(db, write=True):
        DayBook(db).ensure_schema()
        ReadabilityStore(db).ensure_schema()
        VolumeStore(db).ensure_schema()
        LayoutCatalog(db).ensure_schema()
        WorkOrderBook(db).ensure_schema()
        EvidenceBook(db).ensure_schema()
