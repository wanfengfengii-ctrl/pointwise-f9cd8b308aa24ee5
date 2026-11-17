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
from sequence_lab.analysis.execute import analyze_sequence, analyze_anchored
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

            # Joint anchors: requiring both mutually exclusive expansions is
            # contradictory, while a single anchored expansion halves the mass.
            joint_aid = analyze_anchored(db, bref, bc, "branch",
                                         anchors=(("ab", 0, 2), ("ba", 0, 2)),
                                         rule_ids=("ab", "ba"))
            joint = read_report(db, create_report(db, joint_aid))
            assert joint.result == dict(status="impossible", evidence=F(0),
                                        rule_ids=("ab", "ba"), statistics=None)
            single_aid = analyze_anchored(db, bref, bc, "branch",
                                          anchors=(("ab", 0, 2),),
                                          rule_ids=("ab", "ba"))
            single = load_published_analysis(db, single_aid)["result"]
            assert single["evidence"] == F(1, 2)
            assert single["statistics"]["means"] == (F(1), F(0))
            joint_bundle = export_report(db, joint.report_id, output)
            with open_database() as replay:
                parents = joint_bundle["report"]["parents"]
                replay_ref = save_grammar(
                    replay, GrammarRevision.from_record(parents["grammar"]))
                apply_sequences(replay, [SequenceUpdate(**m) for m in parents["cohort"]])
                replay_cohort = freeze_cohort(
                    replay, [m["source_id"] for m in parents["cohort"]])
                replay_aid = analyze_anchored(
                    replay, replay_ref, replay_cohort, parents["member"]["source_id"],
                    anchors=joint_bundle["report"]["request"]["anchors"],
                    rule_ids=joint_bundle["report"]["request"]["rule_ids"])
                replay_result = load_published_analysis(replay, replay_aid)["result"]
            assert replay_result == joint.result
            assert joint_bundle["report"]["parents"]["fixed"]["request"]["anchors"] == (
                ("ab", 0, 2), ("ba", 0, 2))
            print("joint anchors:", joint.result)
            print("single anchor:", single)
            print("offline replay matches:", replay_result == joint.result)
            anchored_payload = dict(
                case_id="anchored-v1",
                input={"sequence": "aa",
                       "anchors": [list(a) for a in
                                   joint_bundle["report"]["request"]["anchors"]],
                       "rule_ids": list(joint_bundle["report"]["request"]["rule_ids"])},
                expected={"status": "impossible", "evidence": "0", "statistics": None,
                          "single_evidence": "1/2", "single_means": ["1", "0"]},
                actual={"status": joint.result["status"],
                        "evidence": str(joint.result["evidence"]),
                        "statistics": joint.result["statistics"],
                        "single_evidence": str(single["evidence"]),
                        "single_means": [str(x) for x in single["statistics"]["means"]]},
                downstream_expected={"offscreen_replay": "impossible"},
                downstream_actual={"offscreen_replay": replay_result["status"]},
                code_paths=["sequence_lab/analysis/anchored.py",
                            "sequence_lab/analysis/request.py",
                            "sequence_lab/delivery/publish.py",
                            "sequence_lab/reporting/export.py"],
                oracle="joint yield-span mask chart over finite trees; exact Fraction")
            print("POINTWISE_ANCHORED " + json.dumps(anchored_payload, ensure_ascii=False,
                                                     sort_keys=True))


if __name__ == "__main__":
    main()
