from fractions import Fraction as F
from dataclasses import replace
from tests.helpers import LabCase, grammar, emit, loop
from sequence_lab.grammar.model import Rule
from sequence_lab.grammar.revisions import save_grammar, load_grammar_revision, GrammarRevisionConflict
from sequence_lab.grammar.validation import GrammarValidationError
from sequence_lab.cohort.records import SequenceUpdate as U
from sequence_lab.cohort.revisions import apply_sequences, load_current_sources, SequenceRevisionConflict
from sequence_lab.cohort.validation import SequenceValidationError
from sequence_lab.cohort.snapshots import (
    freeze_cohort, load_cohort_snapshot, SnapshotSelectionError)
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.delivery.publish import load_published_analysis


class TestInputs(LabCase):
    def test_invalid_grammar_atomicity(self):
        ref, cohort, source = self.prepare(loop())
        original = load_grammar_revision(self.db, ref)
        invalid = [loop(F(24, 25), revision=2),
                   grammar([emit(weight=F(-1))], revision=2),
                   grammar([emit(weight=F(1, 2))], revision=2)]
        for value in invalid:
            with self.assertRaises(GrammarValidationError):
                save_grammar(self.db, value)
        self.assertEqual(save_grammar(self.db, original), ref)
        with self.assertRaises(GrammarRevisionConflict):
            save_grammar(self.db, grammar([emit()]))
        self.assertEqual(self.db.connection.execute("SELECT count(*) FROM grammars").fetchone()[0], 1)
        self.assertEqual(load_grammar_revision(self.db, ref), original)
        aid = analyze_sequence(self.db, ref, cohort, source, ("loop",))
        self.assertEqual(load_published_analysis(self.db, aid)["result"]["evidence"], F(1))

    def test_grammar_input_contract(self):
        good = grammar([emit()])
        invalid = [replace(good, revision=True), replace(good, start="absent"),
                   replace(good, nonterminals=("S", "S")),
                   replace(good, alphabet=("ab",)), replace(good, rules=()),
                   replace(good, rules=(emit(), emit())),
                   replace(good, rules=(Rule("x", "S", "emit", (), F(1)),)),
                   replace(good, rules=(Rule("x", "S", "unary", ("X",), F(1)),)),
                   replace(good, rules=(Rule("x", "S", "emit", ("z",), F(1)),)),
                   replace(good, rules=(Rule("x", "S", "emit", ("a",), 1),)),
                   replace(good, nonterminals=tuple("ABCDEFGHI"))]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(GrammarValidationError):
                save_grammar(self.db, value)
        self.assertEqual(self.db.connection.execute("SELECT count(*) FROM grammars").fetchone()[0], 0)
        nts = tuple("ABCDEFGH")
        rules = tuple(emit(x, x) for x in nts)
        self.assertIsInstance(save_grammar(self.db, grammar(rules, nts=nts, start="A")), int)
        sixteen = tuple(emit(str(i), weight=F(1, 16)) for i in range(16))
        save_grammar(self.db, grammar(sixteen, name="sixteen"))
        with self.assertRaises(GrammarValidationError):
            save_grammar(self.db, grammar(sixteen + (emit("extra", weight=F(0)),),
                                         name="seventeen"))

    def test_unary_support_boundary(self):
        save_grammar(self.db, loop(F(19, 20), name="boundary"))
        with self.assertRaises(GrammarValidationError):
            save_grammar(self.db, loop(F(24, 25), name="outside"))
        acyclic = grammar([Rule("ab", "A", "unary", ("B",), F(49, 50)),
                           emit("a", "A", weight=F(1, 50)), emit("b", "B", "b")],
                          nts=("A", "B"), start="A", name="acyclic")
        save_grammar(self.db, acyclic)
        cyclic = replace(acyclic, grammar_id="cyclic", rules=(
            acyclic.rules[0], acyclic.rules[1],
            Rule("ba", "B", "unary", ("A",), F(49, 50)),
            emit("b", "B", "b", F(1, 50))))
        with self.assertRaises(GrammarValidationError):
            save_grammar(self.db, cyclic)

    def test_revision_conflict_preserves_snapshot(self):
        apply_sequences(self.db, [U("x", 1, "a")])
        cohort = freeze_cohort(self.db, ["x"])
        fixed = load_cohort_snapshot(self.db, cohort)
        with self.assertRaises(SequenceRevisionConflict):
            apply_sequences(self.db, [U("new", 1, "a"), U("x", 1, "b")])
        self.assertNotIn("new", load_current_sources(self.db))
        apply_sequences(self.db, [U("x", 2, "b")])
        self.assertEqual(load_cohort_snapshot(self.db, cohort), fixed)
        self.assertEqual(load_current_sources(self.db)["x"].sequence, "b")

    def test_revision_order_and_recovery(self):
        apply_sequences(self.db, [U("x", 3, "c"), U("x", 1, "a"), U("x", 2, "b")])
        result = apply_sequences(self.db, [U("x", 1, "z"), U("x", 1, "q"), U("x", 3, "c")])
        self.assertEqual(result.changed_ids, ())
        self.assertEqual(result.ignored_records, 2)
        snapshot = freeze_cohort(self.db, ["x"])
        apply_sequences(self.db, [U("x", 4, withdrawn=True)])
        with self.assertRaises(SnapshotSelectionError):
            freeze_cohort(self.db, ["x"])
        apply_sequences(self.db, [U("x", 6, "🙂"), U("x", 5, "é")])
        self.assertEqual(load_current_sources(self.db)["x"].sequence, "🙂")
        member = load_cohort_snapshot(self.db, snapshot).member("x")
        self.assertEqual((member.revision, member.sequence), (3, "c"))

    def test_atomic_batch_conflicts(self):
        apply_sequences(self.db, [U("x", 1, "a")])
        baseline = load_current_sources(self.db)
        batches = [[U("new", 1, "a"), U("x", 1, "b")],
                   [U("x", 1, "b"), U("new", 1, "a")],
                   [U("new", 1, "a"), U("new", 1, "b")],
                   [U("new", 1, "a"), U("new", 1, withdrawn=True)],
                   [U("x", 2, "c"), U("x", 2, "d"), U("x", 3, "e")]]
        for batch in batches:
            with self.assertRaises(SequenceRevisionConflict):
                apply_sequences(self.db, batch)
            self.assertEqual(load_current_sources(self.db), baseline)

    def test_sequence_validation_and_freeze_rejection(self):
        apply_sequences(self.db, [U("x", 2, "a"), U("gone", 1, withdrawn=True)])
        invalid = [U("x", 1, ""), U("x", 1, "a"*25), U("x", True, "a"),
                   U("x", 3, "a", True), U("", 1, "a"), U("x", 3, None)]
        for update in invalid:
            with self.assertRaises(SequenceValidationError):
                apply_sequences(self.db, [U("new", 1, "a"), update])
            self.assertNotIn("new", load_current_sources(self.db))
        before = self.db.connection.execute("SELECT count(*) FROM cohorts").fetchone()[0]
        for ids in (["x", "missing"], ["x", "gone"], ["x", "x"]):
            with self.assertRaises(SnapshotSelectionError):
                freeze_cohort(self.db, ids)
        self.assertEqual(before, self.db.connection.execute(
            "SELECT count(*) FROM cohorts").fetchone()[0])
        apply_sequences(self.db, [U("long", 1, "a"*24)])
        self.assertEqual(len(load_cohort_snapshot(self.db, freeze_cohort(self.db, ["long"]))
                             .member("long").sequence), 24)
