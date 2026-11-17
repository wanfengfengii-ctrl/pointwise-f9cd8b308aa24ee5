import sqlite3
from contextlib import contextmanager
from sequence_lab.delivery.schema import ensure_schema


class Database:
    def __init__(self, path=":memory:"):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            ensure_schema(self.connection)
        except BaseException:
            self.connection.close()
            raise

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError("nested transactions are not supported")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def open_database(path=":memory:"):
    return Database(path)
