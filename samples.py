from fractions import Fraction
from sequence_lab.grammar.model import Rule, GrammarRevision
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences


def example_grammar():
    return GrammarRevision(
        "cape-demo", 1, "S", ("S",), ("a", "b"),
        (Rule("p", "S", "unary", ("S",), Fraction(1, 4)),
         Rule("q", "S", "unary", ("S",), Fraction(1, 4)),
         Rule("emit", "S", "emit", ("a",), Fraction(1, 2))))


def seed_demo(db):
    ref = save_grammar(db, example_grammar())
    apply_sequences(db, [SequenceUpdate("sample_01", 1, "a")])
    return ref
