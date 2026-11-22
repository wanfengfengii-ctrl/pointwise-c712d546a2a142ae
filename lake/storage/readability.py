import sqlite3

from lake.intake.origin import require_name
from lake.storage.integrity import RecordIntegrityError


class VolumeUnavailable(RuntimeError):
    def __init__(self, volume: str) -> None:
        self.volume = volume
        super().__init__(f"volume is offline: {volume!r}")


class ReadabilityStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS volume_access (
                volume TEXT PRIMARY KEY NOT NULL,
                readable INTEGER NOT NULL CHECK (readable IN (0, 1))
            )
        ''')

    def register(self, volume: str) -> None:
        self.db.execute("INSERT INTO volume_access (volume, readable) VALUES (?, 1)", (volume,))

    def set_readable(self, volume: str, readable: bool) -> None:
        require_name(volume, "volume")
        if type(readable) is not bool:
            raise ValueError("volume readability must be a boolean")
        cursor = self.db.execute('''
            UPDATE volume_access SET readable = ? WHERE volume = ?
        ''', (int(readable), volume))
        if cursor.rowcount != 1:
            raise KeyError(f"volume is not in storage: {volume!r}")

    def require_readable(self, volume: str) -> None:
        row = self.db.execute("SELECT readable FROM volume_access WHERE volume = ?", (volume,)).fetchone()
        if row is None:
            raise RecordIntegrityError(f"missing stored volume: {volume!r}")
        if row[0] == 0:
            raise VolumeUnavailable(volume)

    def release(self, volume: str) -> None:
        self.db.execute("DELETE FROM volume_access WHERE volume = ?", (volume,))
