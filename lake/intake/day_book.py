import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FrozenDay:
    day_id: int
    station: str
    batch_id: str
    row_count: int


class DayBook:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS frozen_days (
                day_id INTEGER PRIMARY KEY,
                station TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                row_count INTEGER NOT NULL CHECK (row_count > 0),
                UNIQUE (station, batch_id)
            )
        ''')

    def register(self, station: str, batch_id: str, row_count: int) -> FrozenDay:
        cursor = self.db.execute('''
            INSERT INTO frozen_days (station, batch_id, row_count) VALUES (?, ?, ?)
            ON CONFLICT (station, batch_id) DO NOTHING
        ''', (station, batch_id, row_count))
        if cursor.rowcount != 1:
            raise ValueError(f"station batch is already frozen: {station!r} {batch_id!r}")
        return FrozenDay(cursor.lastrowid, station, batch_id, row_count)

    def get(self, day_id: int) -> FrozenDay:
        if type(day_id) is not int or not 1 <= day_id <= 2**63 - 1:
            raise KeyError(f"unknown frozen day: {day_id!r}")
        row = self.db.execute('''
            SELECT day_id, station, batch_id, row_count FROM frozen_days WHERE day_id = ?
        ''', (day_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown frozen day: {day_id}")
        return FrozenDay(*row)
