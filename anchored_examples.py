"""Hand-calculated calling examples; contains no anchored implementation."""
import sys
from fractions import Fraction as F
from sequence_lab.grammar.model import Rule, GrammarRevision
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.cohort.records import SequenceUpdate
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.delivery.database import open_database
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.reporting.reports import create_report
from sequence_lab.reporting.read import read_report
from sequence_lab.analysis import execute


def result(ids, evidence, means=None, covariance=None):
    return dict(status="impossible" if evidence == 0 else "ok",
                evidence=F(evidence), rule_ids=ids,
                statistics=None if evidence == 0 else
                dict(means=means, covariance=covariance))


def cases():
    branch = GrammarRevision("anchor-branches", 1, "S", ("S", "A", "B"), ("a",),
        (Rule("ab", "S", "binary", ("A", "B"), F(1, 2)),
         Rule("ba", "S", "binary", ("B", "A"), F(1, 2)),
         Rule("ea", "A", "emit", ("a",), F(1)),
         Rule("eb", "B", "emit", ("a",), F(1))))
    geometric = GrammarRevision("anchor-loop", 1, "S", ("S",), ("a",),
        (Rule("loop", "S", "unary", ("S",), F(1, 2)),
         Rule("emit", "S", "emit", ("a",), F(1, 2))))
    split = GrammarRevision("anchor-split", 1, "S", ("S", "A"), ("a",),
        (Rule("join", "S", "binary", ("A", "A"), F(1)),
         Rule("emit", "A", "emit", ("a",), F(1))))
    unicode = GrammarRevision("anchor-unicode", 1, "S", ("S", "A", "B"), ("é", "🙂"),
        (Rule("join", "S", "binary", ("A", "B"), F(1)),
         Rule("ea", "A", "emit", ("é",), F(1)),
         Rule("eb", "B", "emit", ("🙂",), F(1))))
    zero = GrammarRevision("anchor-zero", 1, "S", ("S",), ("a",),
        (Rule("zero", "S", "unary", ("S",), F(0)),
         Rule("emit", "S", "emit", ("a",), F(1))))
    ordinary_branch = result(("ab", "ba"), 1, (F(1, 2), F(1, 2)),
        ((F(1, 4), F(-1, 4)), (F(-1, 4), F(1, 4))))
    return (
        dict(name="exclusive", grammar=branch, sequence="aa",
             anchors=(("ab", 0, 2), ("ba", 0, 2)), ids=("ab", "ba"),
             ordinary=ordinary_branch, anchored=result(("ab", "ba"), 0)),
        dict(name="single-branch", grammar=branch, sequence="aa",
             anchors=(("ab", 0, 2),), ids=("ab", "ba"),
             ordinary=ordinary_branch,
             anchored=result(("ab", "ba"), F(1, 2), (F(1), F(0)),
                             ((F(0), F(0)), (F(0), F(0))))),
        dict(name="repeated-loop", grammar=geometric, sequence="a",
             anchors=(("loop", 0, 1),), ids=("loop",),
             ordinary=result(("loop",), 1, (F(1),), ((F(2),),)),
             anchored=result(("loop",), F(1, 2), (F(2),), ((F(2),),))),
        dict(name="two-leaves", grammar=split, sequence="aa",
             anchors=(("emit", 0, 1), ("emit", 1, 2)), ids=("emit",),
             ordinary=result(("emit",), 1, (F(2),), ((F(0),),)),
             anchored=result(("emit",), 1, (F(2),), ((F(0),),))),
        dict(name="unicode", grammar=unicode, sequence="é🙂",
             anchors=(("eb", 1, 2),), ids=(),
             ordinary=result((), 1, (), ()), anchored=result((), 1, (), ())),
        dict(name="zero-weight", grammar=zero, sequence="a",
             anchors=(("zero", 0, 1),), ids=("zero",),
             ordinary=result(("zero",), 1, (F(0),), ((F(0),),)),
             anchored=result(("zero",), 0)),
    )


def run(anchored=False):
    function = execute.analyze_anchored if anchored else execute.analyze_sequence
    for case in cases():
        with open_database() as db:
            ref = save_grammar(db, case["grammar"])
            apply_sequences(db, [SequenceUpdate("sample", 1, case["sequence"])])
            cohort = freeze_cohort(db, ["sample"])
            args = (db, ref, cohort, "sample")
            if anchored:
                aid = function(*args, anchors=case["anchors"], rule_ids=case["ids"])
            else:
                aid = function(*args, rule_ids=case["ids"])
            published = load_published_analysis(db, aid)
            expected = case["anchored" if anchored else "ordinary"]
            assert published["result"] == expected, (case["name"], published["result"], expected)
            report = read_report(db, create_report(db, aid))
            assert report.result == expected
            if anchored:
                assert published["request"]["request"]["anchors"] == case["anchors"]
                assert report.request["anchors"] == case["anchors"]
            print(case["name"], "anchored" if anchored else "ordinary", repr(report.result))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--anchored"]):
        raise SystemExit("usage: python3.11 -B anchored_examples.py [--anchored]")
    run(bool(sys.argv[1:]))
