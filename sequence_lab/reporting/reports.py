from dataclasses import dataclass
from sequence_lab.reporting.provenance import verify_analysis_provenance, ProvenanceError
from sequence_lab.delivery.codec import encode_value, content_digest


class ReportCreationError(ValueError):
    pass


@dataclass(frozen=True)
class FixedReport:
    report_id: int
    analysis_id: int
    request: dict
    result: dict
    parents: dict

    def canonical_record(self):
        return dict(report_id=self.report_id, analysis_id=self.analysis_id,
                    request=self.request, result=self.result, parents=self.parents)


def create_report(db, analysis_id):
    try:
        with db.transaction() as connection:
            verified = verify_analysis_provenance(db, analysis_id)
            payload = verified.report_payload()
            return connection.execute(
                "INSERT INTO reports(analysis_ref,payload,digest) VALUES(?,?,?)",
                (analysis_id, encode_value(payload), content_digest(payload))).lastrowid
    except ProvenanceError as exc:
        raise ReportCreationError(str(exc)) from exc
