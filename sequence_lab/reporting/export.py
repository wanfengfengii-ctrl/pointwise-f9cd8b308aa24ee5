import os
import tempfile
from pathlib import Path
from sequence_lab.reporting.read import read_report
from sequence_lab.delivery.codec import encode_value, decode_value, content_digest
from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.grammar.validation import validate_grammar
from sequence_lab.grammar.catalog import build_catalog
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.validation import validate_sequence_batch
from sequence_lab.analysis.moments import AnalysisResult


class ReportExportError(ValueError):
    pass


def build_reproduction_bundle(db, report_id):
    report = read_report(db, report_id)
    return dict(format="sequence-lab-reproduction", version=1,
                report=report.canonical_record())


def export_report(db, report_id, output_path, *, fault=None):
    bundle = build_reproduction_bundle(db, report_id)
    text = encode_value(bundle)
    target = Path(output_path)
    temporary = None
    notify = fault if fault is not None else lambda stage: None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".sequence-export-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            midpoint = len(text) // 2
            stream.write(text[:midpoint])
            notify("during_write")
            stream.write(text[midpoint:])
            stream.flush()
            os.fsync(stream.fileno())
        notify("before_replace")
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise ReportExportError(str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return bundle


def load_reproduction_bundle(path):
    bundle = decode_value(Path(path).read_text(encoding="utf-8"))
    try:
        if (type(bundle) is not dict or set(bundle) != {"format", "version", "report"}
                or bundle["format"] != "sequence-lab-reproduction"
                or type(bundle["version"]) is not int or bundle["version"] != 1):
            raise ReportExportError("unsupported reproduction bundle")
        report = bundle["report"]
        if type(report) is not dict or set(report) != {
                "report_id", "analysis_id", "request", "result", "parents"}:
            raise ReportExportError("incomplete report")
        if any(type(report[k]) is not int or report[k] < 1 for k in ("report_id", "analysis_id")):
            raise ReportExportError("invalid report identity")
        parents = report["parents"]
        if type(parents) is not dict or set(parents) != {
                "grammar_ref", "cohort_id", "grammar", "cohort", "member", "fixed"}:
            raise ReportExportError("incomplete parent chain")
        grammar = validate_grammar(GrammarRevision.from_record(parents["grammar"]))
        member = parents["member"]
        validate_sequence_batch([SequenceUpdate(**member)])
        cohort = parents["cohort"]
        if type(cohort) is not tuple:
            raise ReportExportError("invalid cohort record")
        validate_sequence_batch([SequenceUpdate(**m) for m in cohort])
        ids = tuple(m["source_id"] for m in cohort)
        if ids != tuple(sorted(set(ids))) or member not in cohort:
            raise ReportExportError("invalid cohort membership")
        request = report["request"]
        if type(request) is not dict or set(request) != {
                "grammar_ref", "cohort_id", "member_id", "rule_ids"}:
            raise ReportExportError("invalid request")
        build_catalog(grammar).select_ids(request["rule_ids"])
        if (request["grammar_ref"] != parents["grammar_ref"]
                or request["cohort_id"] != parents["cohort_id"]
                or request["member_id"] != member["source_id"]):
            raise ReportExportError("bundle parent identity mismatch")
        expected = dict(request=request, grammar_digest=content_digest(parents["grammar"]),
                        cohort_digest=content_digest(cohort), member_digest=content_digest(member))
        if parents["fixed"] != expected:
            raise ReportExportError("bundle parent fingerprint mismatch")
        result = AnalysisResult.from_record(report["result"])
        if result.rule_ids != request["rule_ids"]:
            raise ReportExportError("bundle rule order mismatch")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ReportExportError(str(exc)) from exc
    return bundle
