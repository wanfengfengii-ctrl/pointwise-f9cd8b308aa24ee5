from dataclasses import dataclass
from sequence_lab.grammar.revisions import load_grammar_revision
from sequence_lab.grammar.catalog import build_catalog
from sequence_lab.cohort.snapshots import load_cohort_snapshot
from sequence_lab.delivery.codec import content_digest


class AnalysisRequestError(ValueError):
    pass


def normalize_anchors(anchors):
    """Validate anchor shape and return the canonical tuple of triples.

    Order is preserved exactly as supplied.  Coordinates must be genuine
    integers (booleans are rejected) with 0 <= i < j.  Bounds against the
    frozen member and rule membership are checked later, where the grammar
    and the fixed member are available.
    """
    if not isinstance(anchors, (list, tuple)):
        raise AnalysisRequestError("anchors must be a list or tuple")
    if len(anchors) > 2:
        raise AnalysisRequestError("at most two anchors are permitted")
    result = []
    for item in anchors:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise AnalysisRequestError("each anchor must be a (rule_id, i, j) triple")
        rule_id, i, j = item
        if not isinstance(rule_id, str) or not rule_id:
            raise AnalysisRequestError("anchor rule identity must be a nonempty string")
        if type(i) is not int or type(j) is not int:
            raise AnalysisRequestError("anchor coordinates must be integers, not booleans")
        if not 0 <= i < j:
            raise AnalysisRequestError("anchor requires 0 <= i < j")
        result.append((rule_id, i, j))
    if len(set(result)) != len(result):
        raise AnalysisRequestError("duplicate anchor")
    return tuple(result)


def canonical_anchors(anchors):
    """Validate a stored anchor payload; require the canonical tuple form."""
    normalized = normalize_anchors(anchors)
    if type(anchors) is not tuple or any(type(item) is not tuple for item in anchors):
        raise AnalysisRequestError("stored anchors must be canonical tuples")
    return normalized


@dataclass(frozen=True)
class AnalysisRequest:
    grammar_ref: int
    cohort_id: int
    member_id: str
    rule_ids: tuple[str, ...] = ()
    anchors: tuple[tuple[str, int, int], ...] | None = None

    def __post_init__(self):
        if isinstance(self.rule_ids, (list, tuple)):
            object.__setattr__(self, "rule_ids", tuple(self.rule_ids))
        if isinstance(self.anchors, (list, tuple)):
            object.__setattr__(
                self, "anchors",
                tuple(item if not isinstance(item, (list, tuple)) else tuple(item)
                      for item in self.anchors))

    def canonical_record(self):
        record = dict(grammar_ref=self.grammar_ref, cohort_id=self.cohort_id,
                      member_id=self.member_id, rule_ids=self.rule_ids)
        if self.anchors is not None:
            record["anchors"] = self.anchors
        return record


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


def validate_anchor_binding(anchors, catalog, sequence):
    """Check rule identity and frozen-member bounds; return normalized anchors."""
    if anchors is None:
        return None
    normalized = normalize_anchors(anchors)
    for rule_id, i, j in normalized:
        if rule_id not in catalog.by_id:
            raise AnalysisRequestError("unknown original rule ID in anchor")
        if not 0 <= i < j <= len(sequence):
            raise AnalysisRequestError("anchor span outside the frozen member")
    return normalized


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
        catalog = build_catalog(grammar)
        catalog.select_ids(request.rule_ids)
        anchors = validate_anchor_binding(request.anchors, catalog, member.sequence)
    except (KeyError, ValueError, TypeError) as exc:
        raise AnalysisRequestError(str(exc)) from exc
    if anchors != request.anchors:
        request = AnalysisRequest(request.grammar_ref, request.cohort_id,
                                  request.member_id, request.rule_ids, anchors)
    return BoundAnalysisInput(request, grammar, snapshot, member)
