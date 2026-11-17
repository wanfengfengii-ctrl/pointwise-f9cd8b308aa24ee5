SCHEMA_VERSION = 1


class UnsupportedSchemaVersion(ValueError):
    pass


_TABLES = (
    """CREATE TABLE IF NOT EXISTS grammars(
        id INTEGER PRIMARY KEY, grammar_id TEXT NOT NULL, revision INTEGER NOT NULL,
        payload TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(grammar_id,revision))""",
    """CREATE TABLE IF NOT EXISTS sources(
        source_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS cohorts(
        id INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY, grammar_ref INTEGER NOT NULL REFERENCES grammars(id),
        cohort_ref INTEGER NOT NULL REFERENCES cohorts(id), member_id TEXT NOT NULL,
        payload TEXT NOT NULL, digest TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS analyses(
        id INTEGER PRIMARY KEY, request_ref INTEGER NOT NULL UNIQUE REFERENCES requests(id),
        payload TEXT NOT NULL, digest TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY, analysis_ref INTEGER NOT NULL REFERENCES analyses(id),
        payload TEXT NOT NULL, digest TEXT NOT NULL)""",
)


def ensure_schema(connection):
    if connection.in_transaction:
        raise RuntimeError("schema initialization requires an idle connection")
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if version not in (0, SCHEMA_VERSION) or (version == 0 and tables):
            raise UnsupportedSchemaVersion("unsupported database schema")
        for statement in _TABLES:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
