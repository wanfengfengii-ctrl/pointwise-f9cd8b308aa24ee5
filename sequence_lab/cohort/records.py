from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SequenceUpdate:
    source_id: str
    revision: int
    sequence: str | None = None
    withdrawn: bool = False

    def canonical_record(self):
        return asdict(self)


@dataclass(frozen=True)
class SourceRevision(SequenceUpdate):
    pass


@dataclass(frozen=True)
class SnapshotMember:
    source_id: str
    revision: int
    sequence: str

    def canonical_record(self):
        return asdict(self)


@dataclass(frozen=True)
class CohortSnapshot:
    cohort_id: int
    members: tuple[SnapshotMember, ...]

    def member(self, source_id):
        for member in self.members:
            if member.source_id == source_id:
                return member
        raise KeyError("source is not a member of this cohort")

    def canonical_record(self):
        return tuple(m.canonical_record() for m in self.members)


@dataclass(frozen=True)
class ApplyResult:
    changed_ids: tuple[str, ...]
    ignored_records: int
