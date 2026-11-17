import anchored_examples
from tests.helpers import LabCase
from sequence_lab.delivery.database import open_database
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_anchored, analyze_sequence
from sequence_lab.delivery.publish import load_published_analysis


class TestDocumentedExamples(LabCase):
    def test_documented_ordinary_and_anchored_cases(self):
        for case in anchored_examples.cases():
            with self.subTest(name=case["name"]), open_database() as db:
                ref = save_grammar(db, case["grammar"])
                apply_sequences(db, [SequenceUpdate("sample", 1, case["sequence"])])
                cohort = freeze_cohort(db, ["sample"])
                ordinary = load_published_analysis(
                    db, analyze_sequence(db, ref, cohort, "sample", case["ids"]))
                self.assertEqual(ordinary["result"], case["ordinary"])
                anchored_id = analyze_anchored(
                    db, ref, cohort, "sample", anchors=case["anchors"],
                    rule_ids=case["ids"])
                published = load_published_analysis(db, anchored_id)
                self.assertEqual(published["result"], case["anchored"])
                self.assertEqual(published["request"]["request"]["anchors"],
                                 case["anchors"])
                from sequence_lab.reporting.reports import create_report
                from sequence_lab.reporting.read import read_report
                report = read_report(db, create_report(db, anchored_id))
                self.assertEqual(report.request["anchors"], case["anchors"])
