from sequence_lab.cohort.records import SnapshotMember, CohortSnapshot
from sequence_lab.cohort.revisions import load_current_sources
from sequence_lab.cohort.validation import validate_sequence_batch
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.delivery.codec import encode_value, decode_value, content_digest


class SnapshotSelectionError(ValueError):
    pass


def freeze_cohort(db, source_ids):
    if not isinstance(source_ids, (tuple, list)) or any(
            not isinstance(x, str) or not x for x in source_ids):
        raise SnapshotSelectionError("source IDs must be a sequence of nonempty strings")
    if len(set(source_ids)) != len(source_ids):
        raise SnapshotSelectionError("duplicate source selection")
    with db.transaction() as connection:
        sources = load_current_sources(db, source_ids)
        members = []
        for source_id in sorted(source_ids):
            source = sources.get(source_id)
            if source is None or source.withdrawn:
                raise SnapshotSelectionError("unknown or withdrawn source")
            members.append(SnapshotMember(source_id, source.revision, source.sequence))
        record = tuple(m.canonical_record() for m in members)
        return connection.execute(
            "INSERT INTO cohorts(payload,digest) VALUES(?,?)",
            (encode_value(record), content_digest(record))).lastrowid


def load_cohort_snapshot(db, cohort_id):
    row = db.connection.execute("SELECT * FROM cohorts WHERE id=?", (cohort_id,)).fetchone()
    if row is None:
        raise KeyError("unknown cohort")
    record = decode_value(row["payload"])
    if type(record) is not tuple or content_digest(record) != row["digest"]:
        raise ValueError("cohort fingerprint mismatch")
    members = tuple(SnapshotMember(**m) for m in record)
    validate_sequence_batch([SequenceUpdate(m.source_id, m.revision, m.sequence) for m in members])
    ids = tuple(m.source_id for m in members)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("invalid cohort member ordering")
    return CohortSnapshot(cohort_id, members)


def load_snapshot_member(db, cohort_id, source_id):
    return load_cohort_snapshot(db, cohort_id).member(source_id)
