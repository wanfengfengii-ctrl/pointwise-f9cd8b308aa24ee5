import json
import tempfile
from pathlib import Path
from fractions import Fraction as F
from samples import seed_demo
from sequence_lab.delivery.database import open_database
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.reporting.reports import create_report
from sequence_lab.reporting.read import read_report
from sequence_lab.reporting.export import export_report, load_reproduction_bundle
from sequence_lab.grammar.model import Rule, GrammarRevision
from sequence_lab.grammar.revisions import save_grammar


def main():
    with tempfile.TemporaryDirectory(prefix="sequence-lab-demo-") as directory:
        path = Path(directory) / "lab.sqlite"
        output = Path(directory) / "report.json"
        with open_database(path) as db:
            ref = seed_demo(db)
            cohort = freeze_cohort(db, ["sample_01"])
            aid = analyze_sequence(db, ref, cohort, "sample_01", ("p", "q"))
            rid = create_report(db, aid)
            report = read_report(db, rid)
            expected = dict(means=(F(1, 2), F(1, 2)),
                            covariance=((F(3, 4), F(1, 4)), (F(1, 4), F(3, 4))))
            assert report.result["evidence"] == 1
            assert report.result["statistics"] == expected
            fixed = report.canonical_record()
            export_report(db, rid, output)
            apply_sequences(db, [SequenceUpdate("sample_01", 2, "b")])
            new_cohort = freeze_cohort(db, ["sample_01"])
            new_aid = analyze_sequence(db, ref, new_cohort, "sample_01", ("p", "q"))
            assert load_published_analysis(db, new_aid)["result"]["status"] == "impossible"
        with open_database(path) as db:
            reopened = read_report(db, rid)
            assert reopened.canonical_record() == fixed
            bundle = export_report(db, rid, output)
            assert load_reproduction_bundle(output) == bundle
            assert bundle["report"]["parents"]["member"]["sequence"] == "a"
            print("POINTWISE_SCENARIO " + json.dumps(dict(
                case_id="v3", input={"sequence": "a", "loop_weights": ["1/4", "1/4"]},
                expected={"evidence": "1", "means": ["1/2", "1/2"],
                          "covariance": [["3/4", "1/4"], ["1/4", "3/4"]]},
                actual={"evidence": str(reopened.result["evidence"]),
                        "means": [str(x) for x in reopened.result["statistics"]["means"]],
                        "covariance": [[str(x) for x in row] for row in
                                       reopened.result["statistics"]["covariance"]]},
                downstream_expected={"old_sequence": "a", "old_revision": 1},
                downstream_actual={"old_sequence": bundle["report"]["parents"]["member"]["sequence"],
                                   "old_revision": bundle["report"]["parents"]["member"]["revision"]},
                code_paths=["sequence_lab/compiler/contributions.py",
                            "sequence_lab/analysis/moments.py",
                            "sequence_lab/reporting/provenance.py",
                            "sequence_lab/reporting/export.py"],
                oracle="negative multinomial counts before emission; fixed source revision"),
                ensure_ascii=False, sort_keys=True))
            branch = GrammarRevision("cape-branch", 1, "S", ("S", "A", "B"), ("a",),
                (Rule("ab", "S", "binary", ("A", "B"), F(1, 2)),
                 Rule("ba", "S", "binary", ("B", "A"), F(1, 2)),
                 Rule("a", "A", "emit", ("a",), F(1)),
                 Rule("b", "B", "emit", ("a",), F(1))))
            bref = save_grammar(db, branch)
            apply_sequences(db, [SequenceUpdate("branch", 1, "aa")])
            bc = freeze_cohort(db, ["branch"])
            ba = analyze_sequence(db, bref, bc, "branch", ("ab", "ba"))
            br = read_report(db, create_report(db, ba))
            assert br.result["statistics"]["covariance"][0][1] == F(-1, 4)
            print("branch covariance:", br.result["statistics"]["covariance"])
            print("new source result: impossible; reopened report sequence:",
                  reopened.parents["member"]["sequence"])


if __name__ == "__main__":
    main()
