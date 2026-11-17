from dataclasses import dataclass
from sequence_lab.grammar.revisions import load_grammar_revision
from sequence_lab.grammar.catalog import build_catalog
from sequence_lab.cohort.snapshots import load_cohort_snapshot
from sequence_lab.delivery.codec import content_digest


class AnalysisRequestError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisRequest:
    grammar_ref: int
    cohort_id: int
    member_id: str
    rule_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if isinstance(self.rule_ids, (list, tuple)):
            object.__setattr__(self, "rule_ids", tuple(self.rule_ids))

    def canonical_record(self):
        return dict(grammar_ref=self.grammar_ref, cohort_id=self.cohort_id,
                    member_id=self.member_id, rule_ids=self.rule_ids)


@dataclass(frozen=True)
class BoundAnalysisInput:
    request: AnalysisRequest
    grammar: object
    snapshot: object
    member: object

    def canonical_record(self):
        return dict(request=self.request.canonical_record(),
                    grammar_digest=content_digest(self.grammar.canonical_record()),
                    cohort_digest=content_digest(self.snapshot.canonical_record()),
                    member_digest=content_digest(self.member.canonical_record()))


def bind_analysis_request(db, request):
    if not isinstance(request, AnalysisRequest):
        raise AnalysisRequestError("expected AnalysisRequest")
    if any(type(x) is not int or x < 1 for x in (request.grammar_ref, request.cohort_id)):
        raise AnalysisRequestError("invalid fixed input identity")
    if not isinstance(request.member_id, str) or not request.member_id:
        raise AnalysisRequestError("invalid member identity")
    try:
        grammar = load_grammar_revision(db, request.grammar_ref)
        snapshot = load_cohort_snapshot(db, request.cohort_id)
        member = snapshot.member(request.member_id)
        build_catalog(grammar).select_ids(request.rule_ids)
    except (KeyError, ValueError, TypeError) as exc:
        raise AnalysisRequestError(str(exc)) from exc
    return BoundAnalysisInput(request, grammar, snapshot, member)
