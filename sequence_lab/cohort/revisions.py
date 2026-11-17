from sequence_lab.cohort.records import SourceRevision, ApplyResult
from sequence_lab.cohort.validation import (
    validate_sequence_batch, check_batch_conflicts, SequenceValidationError)
from sequence_lab.delivery.codec import encode_value, decode_value


class SequenceRevisionConflict(SequenceValidationError):
    pass


def load_current_sources(db, source_ids=None):
    if source_ids is None:
        rows = db.connection.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
    else:
        rows = []
        for source_id in source_ids:
            row = db.connection.execute(
                "SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if row is not None:
                rows.append(row)
    result = {}
    for row in rows:
        source = SourceRevision(**decode_value(row["payload"]))
        validate_sequence_batch([source])
        if source.source_id != row["source_id"] or source.revision != row["revision"]:
            raise ValueError("source identity mismatch")
        result[source.source_id] = source
    return result


def plan_sequence_updates(current, updates):
    eligible, ignored = [], 0
    for update in updates:
        baseline = current.get(update.source_id)
        if baseline is not None and update.revision < baseline.revision:
            ignored += 1
        else:
            eligible.append(update)
    try:
        check_batch_conflicts(eligible)
    except SequenceValidationError as exc:
        raise SequenceRevisionConflict(str(exc)) from exc
    planned = {}
    for update in sorted(eligible, key=lambda u: (u.source_id, u.revision)):
        baseline = current.get(update.source_id)
        if baseline is not None and update.revision == baseline.revision:
            if update.canonical_record() != baseline.canonical_record():
                raise SequenceRevisionConflict("same source revision has different content")
        previous = planned.get(update.source_id, baseline)
        if previous is None or update.revision > previous.revision:
            planned[update.source_id] = SourceRevision(**update.canonical_record())
    return planned, ignored


def apply_sequences(db, updates):
    updates = validate_sequence_batch(updates)
    with db.transaction() as connection:
        current = load_current_sources(db, sorted({u.source_id for u in updates}))
        planned, ignored = plan_sequence_updates(current, updates)
        for source_id, source in planned.items():
            connection.execute(
                """INSERT INTO sources(source_id,revision,payload) VALUES(?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                   revision=excluded.revision,payload=excluded.payload""",
                (source_id, source.revision, encode_value(source.canonical_record())))
        return ApplyResult(tuple(sorted(planned)), ignored)
