import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def transaction(db: sqlite3.Connection, *, write: bool = False) -> Iterator[None]:
    if db.in_transaction:
        raise RuntimeError("lake operations require an idle connection")
    db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise
