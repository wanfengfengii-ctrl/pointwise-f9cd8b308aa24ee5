from sequence_lab.reporting.reports import FixedReport
from sequence_lab.reporting.provenance import verify_report_provenance
from sequence_lab.delivery.codec import decode_value


class ReportNotFound(KeyError):
    pass


def read_report(db, report_id):
    row = db.connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if row is None:
        raise ReportNotFound("unknown report")
    payload = decode_value(row["payload"])
    verify_report_provenance(db, row["analysis_ref"], payload, row["digest"])
    return FixedReport(row["id"], **payload)
