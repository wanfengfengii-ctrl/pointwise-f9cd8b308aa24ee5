from sequence_lab.cohort.records import SequenceUpdate


class SequenceValidationError(ValueError):
    pass


def validate_sequence_batch(updates):
    if not isinstance(updates, (list, tuple)):
        raise SequenceValidationError("batch must be a sequence")
    result = tuple(updates)
    for update in result:
        if not isinstance(update, SequenceUpdate):
            raise SequenceValidationError("expected SequenceUpdate")
        if not isinstance(update.source_id, str) or not update.source_id:
            raise SequenceValidationError("source ID required")
        if type(update.revision) is not int or update.revision < 1:
            raise SequenceValidationError("revision must be a positive integer")
        if type(update.withdrawn) is not bool:
            raise SequenceValidationError("withdrawn must be boolean")
        if update.withdrawn:
            if update.sequence is not None:
                raise SequenceValidationError("withdrawal cannot include sequence")
        elif not isinstance(update.sequence, str) or not 1 <= len(update.sequence) <= 24:
            raise SequenceValidationError("sequence must contain 1..24 Unicode codepoints")
    return result


def check_batch_conflicts(updates):
    seen = {}
    for update in updates:
        key = (update.source_id, update.revision)
        record = update.canonical_record()
        if key in seen and seen[key] != record:
            raise SequenceValidationError("conflicting records in batch")
        seen[key] = record
    return seen
