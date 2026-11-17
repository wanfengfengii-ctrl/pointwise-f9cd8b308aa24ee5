import unittest
from fractions import Fraction as F
from sequence_lab.delivery.database import open_database
from sequence_lab.grammar.model import Rule, GrammarRevision
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.reporting.reports import create_report
from sequence_lab.reporting.read import read_report


def grammar(rules, nts=("S",), alphabet=("a", "b"), name="g", revision=1, start="S"):
    return GrammarRevision(name, revision, start, nts, alphabet, tuple(rules))


def emit(rule_id="emit", lhs="S", char="a", weight=F(1)):
    return Rule(rule_id, lhs, "emit", (char,), weight)


def loop(q=F(1, 2), name="g", revision=1):
    return grammar([Rule("loop", "S", "unary", ("S",), q),
                    emit(weight=1-q)], name=name, revision=revision)


def parallel():
    return grammar([Rule("p", "S", "unary", ("S",), F(1, 4)),
                    Rule("q", "S", "unary", ("S",), F(1, 4)),
                    Rule("zero", "S", "unary", ("S",), F(0)),
                    emit(weight=F(1, 2))])


def branches():
    return grammar([Rule("ab", "S", "binary", ("A", "B"), F(1, 2)),
                    Rule("ba", "S", "binary", ("B", "A"), F(1, 2)),
                    emit("ea", "A"), emit("eb", "B")], nts=("S", "A", "B"))


class LabCase(unittest.TestCase):
    def setUp(self):
        self.db = open_database()

    def tearDown(self):
        self.db.close()

    def prepare(self, value, sequence="a", source="sample"):
        ref = save_grammar(self.db, value)
        current = self.db.connection.execute(
            "SELECT revision FROM sources WHERE source_id=?", (source,)).fetchone()
        revision = current[0] + 1 if current else 1
        apply_sequences(self.db, [SequenceUpdate(source, revision, sequence)])
        cohort = freeze_cohort(self.db, [source])
        return ref, cohort, source

    def analyze(self, value, sequence, ids):
        binding = self.prepare(value, sequence)
        analysis_id = analyze_sequence(self.db, *binding, ids)
        published = load_published_analysis(self.db, analysis_id)
        report = read_report(self.db, create_report(self.db, analysis_id))
        self.assertEqual(published["result"], report.result)
        return published["result"]
