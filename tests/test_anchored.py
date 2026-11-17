from fractions import Fraction as F
from dataclasses import replace
from tests.helpers import LabCase, grammar, emit, branches
from sequence_lab.grammar.model import Rule
from sequence_lab.cohort.records import SequenceUpdate as U
from sequence_lab.analysis.execute import analyze_anchored


def _enumerate(grammar_value, sequence, rule_ids):
    """Independent finite-tree enumerator for acyclic grammars.

    Returns (weight, counts, applications) tuples where applications is the
    set of (rule_id, i, j) yield spans at which the rule is applied.  The
    grammar must be unary-acyclic, or recursion will not terminate.

    Raises RecursionError on grammars that contain a unary cycle.
    """
    rules = list(grammar_value.rules)
    ids = tuple(rule_ids)

    def merge(a, b):
        wa, ca, aa = a
        wb, cb, ab = b
        return (wa * wb,
                tuple(x + y for x, y in zip(ca, cb)),
                aa | ab)

    def span(nt, i, j):
        results = []
        for rule in rules:
            if rule.lhs != nt or rule.weight == 0:
                continue
            counts = tuple(F(int(rule.rule_id == rid)) for rid in ids)
            own = frozenset({(rule.rule_id, i, j)})
            if rule.kind == "emit":
                if j == i + 1 and rule.rhs[0] == sequence[i]:
                    results.append((rule.weight, counts, own))
            elif rule.kind == "unary":
                for child in span(rule.rhs[0], i, j):
                    results.append(merge((rule.weight, counts, own), child))
            else:
                for k in range(i + 1, j):
                    for left in span(rule.rhs[0], i, k):
                        for right in span(rule.rhs[1], k, j):
                            results.append(merge(merge((rule.weight, counts, own),
                                                       left), right))
        return results

    return span(grammar_value.start, 0, len(sequence))


def _expected(grammar_value, sequence, anchors, rule_ids):
    trees = _enumerate(grammar_value, sequence, rule_ids)
    wanted = set(anchors)
    kept = [t for t in trees if wanted <= t[2]]
    evidence = sum((t[0] for t in kept), F(0))
    if evidence == 0:
        return dict(status="impossible", evidence=F(0), rule_ids=tuple(rule_ids),
                    statistics=None)
    d = len(rule_ids)
    means = tuple(sum((t[1][r] * t[0] for t in kept), F(0)) / evidence
                  for r in range(d))
    covariance = tuple(
        tuple(sum((t[1][r] * t[1][s] * t[0] for t in kept), F(0)) / evidence
              - means[r] * means[s] for s in range(d)) for r in range(d))
    return dict(status="ok", evidence=evidence, rule_ids=tuple(rule_ids),
                statistics=dict(means=means, covariance=covariance))


def rich_grammar(name="rich"):
    return grammar([Rule("ab", "S", "binary", ("A", "B"), F(1, 3)),
                    Rule("ba", "S", "binary", ("B", "A"), F(2, 3)),
                    Rule("lift", "B", "unary", ("A",), F(1, 2)),
                    emit("ea", "A"), emit("eb", "B", "a", F(1, 2))],
                   nts=("S", "A", "B"), name=name)


def chain_grammar(name="chain"):
    return grammar([Rule("join", "S", "binary", ("X", "Y"), F(1, 2)),
                    Rule("u", "S", "unary", ("A",), F(1, 2)),
                    emit("x", "X"), emit("y", "Y", "b"),
                    Rule("u2", "A", "unary", ("B",), F(1, 3)),
                    emit("a2", "A", weight=F(2, 3)), emit("b2", "B")],
                   nts=("S", "X", "Y", "A", "B"), name=name, start="S")


class TestAnchored(LabCase):
    def anchored(self, value, sequence, anchors, ids=()):
        binding = self.prepare(value, sequence)
        aid = analyze_anchored(self.db, *binding, anchors=anchors, rule_ids=ids)
        from sequence_lab.delivery.publish import load_published_analysis
        return load_published_analysis(self.db, aid)

    def test_enumeration_matches_rich_acyclic_grammar(self):
        value = rich_grammar()
        sequences = ("a", "aa", "ab", "ba", "bb")
        choices = [(), ("ab",), ("ba",), ("lift",), ("ea",), ("eb",),
                   ("ab", "ba"), ("lift", "eb"), ("ea", "eb")]
        for sequence in sequences:
            for ids in choices:
                for anchors in [(), (("ab", 0, 2),), (("ea", 0, 1),),
                                (("ea", 1, 2),), (("lift", 1, 2),),
                                (("ab", 0, 2), ("ea", 0, 1)),
                                (("ba", 0, 2), ("lift", 1, 2)),
                                (("eb", 0, 1), ("eb", 1, 2))]:
                    if any(j > len(sequence) for _, _, j in anchors):
                        continue
                    with self.subTest(sequence=sequence, ids=ids, anchors=anchors):
                        published = self.anchored(value, sequence, anchors, ids)
                        self.assertEqual(published["result"],
                                         _expected(value, sequence, anchors, ids))

    def test_enumeration_matches_deep_unary_chain(self):
        value = chain_grammar()
        cases = [("a", (), (("u2", 0, 1),)),
                 ("a", ("u", "u2"), (("u2", 0, 1), ("b2", 0, 1))),
                 ("a", ("b2",), (("b2", 0, 1),)),
                 ("ab", ("join",), (("join", 0, 2), ("u2", 0, 1))),
                 ("b", (), (("y", 0, 1),))]
        for sequence, ids, anchors in cases:
            with self.subTest(sequence=sequence, anchors=anchors):
                published = self.anchored(value, sequence, anchors, ids)
                self.assertEqual(published["result"],
                                 _expected(value, sequence, anchors, ids))

    def test_loop_hand_calculation(self):
        q = F(2, 5)
        value = grammar([Rule("loop", "S", "unary", ("S",), q),
                         emit("emit", weight=1 - q)], name="hand")
        result = self.anchored(value, "a", (("loop", 0, 1),), ("loop",))["result"]
        self.assertEqual(result["evidence"], q)
        self.assertEqual(result["statistics"]["means"], (F(1) / (1 - q),))
        self.assertEqual(result["statistics"]["covariance"],
                         ((q / (1 - q) ** 2,),))
        # Anchoring the root emission is satisfied by every parse.
        other = self.anchored(value, "a", (("emit", 0, 1),), ("loop", "emit"))["result"]
        self.assertEqual(other["evidence"], F(1))
        self.assertEqual(other["statistics"]["means"], (q / (1 - q), F(1)))
        self.assertEqual(other["statistics"]["covariance"],
                         ((q / (1 - q) ** 2, F(0)), (F(0), F(0))))
        both = self.anchored(value, "a", (("emit", 0, 1), ("loop", 0, 1)),
                             ("loop",))["result"]
        self.assertEqual(both, dict(status="ok", evidence=q,
                                    rule_ids=("loop",),
                                    statistics=dict(
                                        means=(F(1) / (1 - q),),
                                        covariance=((q / (1 - q) ** 2,),))))

    def test_joint_contradiction_and_single_branch(self):
        value = branches()
        exclusive = self.anchored(value, "aa",
                                  (("ab", 0, 2), ("ba", 0, 2)), ("ab", "ba"))
        self.assertEqual(exclusive["result"], dict(
            status="impossible", evidence=F(0), rule_ids=("ab", "ba"),
            statistics=None))
        single = self.anchored(value, "aa", (("ab", 0, 2),), ("ab", "ba"))["result"]
        self.assertEqual(single["evidence"], F(1, 2))
        self.assertEqual(single["statistics"]["means"], (F(1), F(0)))
        self.assertEqual(single["statistics"]["covariance"],
                         ((F(0), F(0)), (F(0), F(0))))

    def test_empty_and_reordered_anchors(self):
        for value, sequence, ids in ((rich_grammar("e1"), "aa", ("ab", "ba")),
                                     (rich_grammar("e2"), "a", ("ea",)),
                                     (chain_grammar("e3"), "a", ("u2",))):
            self.analyze(value, sequence, ids)
        value = rich_grammar("reorder")
        normal = self.anchored(value, "aa", (("ab", 0, 2), ("ea", 0, 1)),
                               ("ab", "ea"))["result"]
        swapped = self.anchored(value, "aa", (("ea", 0, 1), ("ab", 0, 2)),
                                ("ab", "ea"))["result"]
        self.assertEqual(normal, swapped)
        empty = self.anchored(value, "aa", (), ("ab",))["result"]
        self.assertEqual(empty, self.analyze(value, "aa", ("ab",)))

    def test_two_loops_hand_calculation(self):
        q = r = F(1, 4)
        p = 1 - q - r
        value = grammar([Rule("loop", "S", "unary", ("S",), q),
                         Rule("other", "S", "unary", ("S",), r),
                         emit("emit", weight=p)], name="two-loops")
        # Negative-multinomial node counts (a loops of type 1, b of type 2,
        # then the emission).  Conditioning on loop >= 1 keeps A's moments and
        # removes the A = 0 geometric tail of B.
        single = self.anchored(value, "a", (("loop", 0, 1),),
                               ("loop", "other"))["result"]
        self.assertEqual(single["evidence"], q / (1 - r))
        self.assertEqual(single["statistics"]["means"], (F(3, 2), F(5, 6)))
        self.assertEqual(single["statistics"]["covariance"],
                         ((F(3, 4), F(1, 4)), (F(1, 4), F(43, 36))))
        joint = self.anchored(value, "a", (("loop", 0, 1), ("other", 0, 1)),
                              ("loop", "other"))["result"]
        # P(A>=1 and B>=1) = 1 - P(A=0) - P(B=0) + P(A=B=0) = 1/6 here.
        self.assertEqual(joint["evidence"], F(1, 6))
        self.assertEqual(joint["statistics"]["means"], (F(5, 3), F(5, 3)))
        self.assertEqual(joint["statistics"]["covariance"],
                         ((F(1), F(2, 9)), (F(2, 9), F(1))))
        # Symmetry: swapping the two anchors' order changes nothing.
        swapped = self.anchored(value, "a", (("other", 0, 1), ("loop", 0, 1)),
                                ("other", "loop"))["result"]
        self.assertEqual(swapped["evidence"], joint["evidence"])
        self.assertEqual(swapped["statistics"]["covariance"],
                         tuple(tuple(reversed(row)) for row in
                               reversed(joint["statistics"]["covariance"])))

    def test_zero_weight_anchor_is_legitimate_but_empty(self):
        value = grammar([Rule("zero", "S", "unary", ("S",), F(0)),
                         emit("emit", "S", "a", F(1))], name="zero")
        self.assertEqual(self.anchored(value, "a", (("zero", 0, 1),),
                                       ("zero",))["result"],
                         dict(status="impossible", evidence=F(0),
                              rule_ids=("zero",), statistics=None))
        self.assertEqual(self.anchored(value, "a", (("emit", 0, 1),),
                                       ("zero", "emit"))["result"]
                         ["statistics"]["means"], (F(0), F(1)))

    def test_unicode_codepoint_spans(self):
        value = grammar([Rule("join", "S", "binary", ("A", "B"), F(1)),
                         emit("ea", "A", "é"), emit("eb", "B", "🙂")],
                        nts=("S", "A", "B"), alphabet=("é", "🙂"), name="uni")
        result = self.anchored(value, "é🙂", (("eb", 1, 2),), ())["result"]
        self.assertEqual(result, dict(status="ok", evidence=F(1), rule_ids=(),
                                      statistics=dict(means=(), covariance=())))
        self.assertEqual(self.anchored(value, "é🙂", (("eb", 0, 1),), ())["result"]
                         ["status"], "impossible")
