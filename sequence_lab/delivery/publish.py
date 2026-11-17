from sequence_lab.delivery.codec import encode_value, decode_value, content_digest
from sequence_lab.analysis.request import AnalysisRequest, bind_analysis_request
from sequence_lab.analysis.moments import AnalysisResult


class AnalysisPublicationError(ValueError):
    pass


def publish_analysis(db, bound, result, fault=None):
    result.validate()
    if result.rule_ids != bound.request.rule_ids:
        raise AnalysisPublicationError("result request mismatch")
    fixed = bound.canonical_record()
    value = result.canonical_record()
    notify = fault if fault is not None else lambda stage: None
    with db.transaction() as connection:
        current = bind_analysis_request(db, bound.request)
        if current.canonical_record() != fixed:
            raise AnalysisPublicationError("fixed inputs changed before publication")
        request_id = connection.execute(
            """INSERT INTO requests(grammar_ref,cohort_ref,member_id,payload,digest)
               VALUES(?,?,?,?,?)""",
            (bound.request.grammar_ref, bound.request.cohort_id, bound.request.member_id,
             encode_value(fixed), content_digest(fixed))).lastrowid
        notify("after_request")
        analysis_id = connection.execute(
            "INSERT INTO analyses(request_ref,payload,digest) VALUES(?,?,?)",
            (request_id, encode_value(value),
             content_digest(dict(request=fixed, result=value)))).lastrowid
        notify("after_result")
        notify("before_commit")
        return analysis_id


def load_published_analysis(db, analysis_id):
    row = db.connection.execute(
        """SELECT a.id,a.request_ref,a.payload AS result,a.digest AS result_digest,
                  r.grammar_ref,r.cohort_ref,r.member_id,r.payload AS request,
                  r.digest AS request_digest
           FROM analyses a JOIN requests r ON a.request_ref=r.id WHERE a.id=?""",
        (analysis_id,)).fetchone()
    if row is None:
        raise KeyError("unknown or incomplete published analysis")
    fixed, value = decode_value(row["request"]), decode_value(row["result"])
    if content_digest(fixed) != row["request_digest"]:
        raise AnalysisPublicationError("request fingerprint mismatch")
    if type(fixed) is not dict or set(fixed) != {
            "request", "grammar_digest", "cohort_digest", "member_digest"}:
        raise AnalysisPublicationError("invalid fixed request structure")
    request = AnalysisRequest(**fixed["request"])
    if (request.grammar_ref, request.cohort_id, request.member_id) != (
            row["grammar_ref"], row["cohort_ref"], row["member_id"]):
        raise AnalysisPublicationError("request parent identity mismatch")
    result = AnalysisResult.from_record(value)
    if result.rule_ids != request.rule_ids:
        raise AnalysisPublicationError("published rule order mismatch")
    if content_digest(dict(request=fixed, result=value)) != row["result_digest"]:
        raise AnalysisPublicationError("analysis fingerprint mismatch")
    return dict(analysis_id=row["id"], request_id=row["request_ref"],
                request=fixed, result=value)
