from dataclasses import dataclass
from sequence_lab.delivery.codec import content_digest
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.analysis.request import AnalysisRequest, bind_analysis_request


class ProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedProvenance:
    analysis: dict
    grammar: object
    snapshot: object
    member: object

    def parent_record(self):
        request = self.analysis["request"]["request"]
        return dict(grammar_ref=request["grammar_ref"], cohort_id=request["cohort_id"],
                    grammar=self.grammar.canonical_record(),
                    cohort=self.snapshot.canonical_record(),
                    member=self.member.canonical_record(),
                    fixed=self.analysis["request"])

    def report_payload(self):
        return dict(analysis_id=self.analysis["analysis_id"],
                    request=self.analysis["request"]["request"],
                    result=self.analysis["result"], parents=self.parent_record())


def verify_analysis_provenance(db, analysis_id):
    try:
        analysis = load_published_analysis(db, analysis_id)
        request = AnalysisRequest(**analysis["request"]["request"])
        bound = bind_analysis_request(db, request)
        if bound.canonical_record() != analysis["request"]:
            raise ProvenanceError("analysis fixed parent fingerprint mismatch")
        return VerifiedProvenance(analysis, bound.grammar, bound.snapshot, bound.member)
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ProvenanceError(str(exc)) from exc


def verify_report_provenance(db, analysis_id, payload, digest):
    if content_digest(payload) != digest:
        raise ProvenanceError("report fingerprint mismatch")
    verified = verify_analysis_provenance(db, analysis_id)
    if payload != verified.report_payload():
        raise ProvenanceError("report/analysis parent chain mismatch")
    return verified
