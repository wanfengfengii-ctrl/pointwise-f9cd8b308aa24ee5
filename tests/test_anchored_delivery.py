import json
import sys
import tempfile
from pathlib import Path
from fractions import Fraction as F
from tests.helpers import LabCase, grammar, emit, branches
from sequence_lab.grammar.model import Rule
from sequence_lab.cohort.records import SequenceUpdate as U
from sequence_lab.cohort.revisions import apply_sequences
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_anchored, analyze_sequence
from sequence_lab.analysis.request import AnalysisRequestError
from sequence_lab.delivery.database import open_database
from sequence_lab.delivery.codec import encode_value, content_digest
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.reporting.reports import create_report, ReportCreationError
from sequence_lab.reporting.read import read_report
from sequence_lab.reporting.export import export_report, load_reproduction_bundle, ReportExportError
from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.grammar.revisions import save_grammar


def _counts(db):
    return tuple(db.connection.execute(
        "SELECT count(*) FROM " + table).fetchone()[0]
        for table in ("requests", "analyses", "reports"))


class TestAnchoredDelivery(LabCase):
    def test_invalid_anchors_rejected_without_publication(self):
        binding = self.prepare(branches(), "aa")
        bad = [
            [("ab", 0, 2), ("ab", 0, 2)],       # duplicate triple
            [("ab", 0, 2), ("ba", 0, 2), ("ea", 0, 1)],  # three anchors
            [("ab", 0, 2, 3)],                  # wrong arity
            [("ab", 0)],                        # wrong arity
            [("ab", True, 2)],                  # boolean coordinate
            [("ab", 0, True)],
            [("ab", 0.0, 2)],                   # non-int coordinate
            [("ab", -1, 2)],                    # negative
            [("ab", 2, 2)],                     # empty span
            [("ab", 2, 1)],                     # reversed
            [("ab", 0, 3)],                     # beyond member
            [("absent", 0, 1)],                 # unknown rule
            [("", 0, 1)],                       # empty identity
            [(1, 0, 1)],                        # non-string identity
            "ab",                               # not a sequence of triples
            [("ab", 0, 2), ("ab", 0, 2, )],     # duplicate plus malformed
        ]
        before = _counts(self.db)
        for anchors in bad:
            with self.subTest(anchors=anchors), self.assertRaises(AnalysisRequestError):
                analyze_anchored(self.db, *binding, anchors=anchors)
        for ids in (("ab", "ab"), ("ab", "ba", "ea"), ("absent",)):
            with self.assertRaises(AnalysisRequestError):
                analyze_anchored(self.db, *binding, anchors=(("ab", 0, 2),), rule_ids=ids)
        self.assertEqual(_counts(self.db), before)
        self.assertEqual(before, (0, 0, 0))

    def test_same_rule_two_spans_allowed(self):
        value = grammar([Rule("join", "S", "binary", ("A", "A"), F(1)),
                         emit("e", "A")], nts=("S", "A"), name="same")
        binding = self.prepare(value, "aa")
        aid = analyze_anchored(self.db, *binding,
                               anchors=(("e", 0, 1), ("e", 1, 2)), rule_ids=("e",))
        published = load_published_analysis(self.db, aid)
        self.assertEqual(published["result"]["statistics"]["means"], (F(2),))
        self.assertEqual(published["request"]["request"]["anchors"],
                         (("e", 0, 1), ("e", 1, 2)))

    def test_failure_points_roll_back_and_retry(self):
        binding = self.prepare(branches(), "aa")
        for stage in ("after_request", "after_result", "before_commit"):
            def fail(actual, target=stage):
                if actual == target:
                    raise RuntimeError(target)
            with self.assertRaises(RuntimeError):
                analyze_anchored(self.db, *binding, anchors=(("ab", 0, 2),),
                                 fault=fail)
            self.assertEqual(_counts(self.db), (0, 0, 0))
        aid = analyze_anchored(self.db, *binding, anchors=(("ab", 0, 2),),
                               rule_ids=("ab", "ba"))
        self.assertEqual(read_report(self.db, create_report(self.db, aid)).result,
                         dict(status="ok", evidence=F(1, 2),
                              rule_ids=("ab", "ba"),
                              statistics=dict(means=(F(1), F(0)),
                                              covariance=((F(0), F(0)),
                                                          (F(0), F(0))))))

    def test_reopen_correction_and_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lab.sqlite"
            output = Path(directory) / "bundle.json"
            with open_database(path) as db:
                ref = save_grammar(db, branches())
                apply_sequences(db, [U("x", 1, "aa")])
                cohort = freeze_cohort(db, ["x"])
                aid = analyze_anchored(db, ref, cohort, "x",
                                       anchors=(("ab", 0, 2),), rule_ids=("ab", "ba"))
                rid = create_report(db, aid)
                fixed = read_report(db, rid).canonical_record()
                self.assertEqual(fixed["request"]["anchors"], (("ab", 0, 2),))
                self.assertEqual(fixed["parents"]["fixed"]["request"]["anchors"],
                                 (("ab", 0, 2),))
                apply_sequences(db, [U("x", 2, "bb")])
                new_cohort = freeze_cohort(db, ["x"])
                new_aid = analyze_anchored(db, ref, new_cohort, "x",
                                           anchors=(("ab", 0, 2),))
                self.assertEqual(load_published_analysis(db, new_aid)["result"]
                                 ["status"], "impossible")
            with open_database(path) as db:
                calls = []
                def guard(frame, event, arg):
                    if event == "call" and frame.f_code.co_name in {
                            "analyze_anchored", "compile_grammar", "compute_anchored_result",
                            "compute_evidence", "compute_moments"}:
                        calls.append(frame.f_code.co_name)
                        raise AssertionError("read attempted inference")
                previous = sys.getprofile()
                sys.setprofile(guard)
                try:
                    reopened = read_report(db, rid)
                    self.assertEqual(reopened.canonical_record(), fixed)
                    bundle = export_report(db, rid, output)
                    self.assertEqual(load_reproduction_bundle(output), bundle)
                finally:
                    sys.setprofile(previous)
                self.assertEqual(calls, [])
                self.assertEqual(bundle["report"]["request"]["anchors"],
                                 (("ab", 0, 2),))
                self.assertEqual(bundle["report"]["parents"]["fixed"]["request"]
                                 ["anchors"], (("ab", 0, 2),))
                with open_database() as replay:
                    parents = bundle["report"]["parents"]
                    replay_ref = save_grammar(
                        replay, GrammarRevision.from_record(parents["grammar"]))
                    apply_sequences(replay, [U(**m) for m in parents["cohort"]])
                    replay_cohort = freeze_cohort(
                        replay, [m["source_id"] for m in parents["cohort"]])
                    replay_aid = analyze_anchored(
                        replay, replay_ref, replay_cohort,
                        parents["member"]["source_id"],
                        anchors=reopened.request["anchors"],
                        rule_ids=reopened.request["rule_ids"])
                    self.assertEqual(load_published_analysis(replay, replay_aid)["result"],
                                     reopened.result)
                # Reading never re-derives the answer from current sources.
                self.assertEqual(reopened.parents["member"]["sequence"], "aa")
                self.assertEqual(reopened.parents["member"]["revision"], 1)

    def test_old_records_keep_exact_payload(self):
        binding = self.prepare(branches(), "aa")
        aid = analyze_sequence(self.db, *binding, ("ab", "ba"))
        published = load_published_analysis(self.db, aid)
        self.assertNotIn("anchors", published["request"])
        self.assertNotIn("anchors", published["request"]["request"])
        report = read_report(self.db, create_report(self.db, aid))
        self.assertNotIn("anchors", report.request)
        self.assertEqual(report.result["evidence"], F(1))

    def test_bundle_rejects_tampered_anchors(self):
        binding = self.prepare(branches(), "aa")
        aid = analyze_anchored(self.db, *binding, anchors=(("ab", 0, 2),))
        rid = create_report(self.db, aid)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bundle.json"
            export_report(self.db, rid, target)
            original = load_reproduction_bundle(target)
            mutations = []
            bundle = load_reproduction_bundle(target)
            # Change only the surface anchor tuple; the parent fingerprint still
            # records the original, so admission must reject the disagreement.
            bundle["report"]["request"]["anchors"] = (("ba", 0, 2),)
            mutations.append(bundle)
            bundle2 = load_reproduction_bundle(target)
            bundle2["report"]["parents"]["fixed"]["request"]["anchors"] = (("ba", 0, 2),)
            mutations.append(bundle2)
            # Both copies changed but to an invalid/duplicated triple shape.
            bundle3 = load_reproduction_bundle(target)
            bundle3["report"]["request"]["anchors"] = (("ab", 0, 2), ("ab", 0, 2))
            bundle3["report"]["parents"]["fixed"]["request"]["anchors"] = (
                ("ab", 0, 2), ("ab", 0, 2))
            fixed3 = dict(bundle3["report"]["parents"]["fixed"])
            fixed3["request"] = dict(fixed3["request"],
                                     anchors=(("ab", 0, 2), ("ab", 0, 2)))
            bundle3["report"]["parents"]["fixed"] = fixed3
            bundle3["report"]["parents"] = dict(bundle3["report"]["parents"])
            mutations.append(bundle3)
            for value in mutations:
                target.write_text(encode_value(value), encoding="utf-8")
                with self.assertRaises(ReportExportError):
                    load_reproduction_bundle(target)
            target.write_text(encode_value(original), encoding="utf-8")
            self.assertEqual(load_reproduction_bundle(target), original)

    def test_duplicate_anchor_payload_rejected_when_reading(self):
        binding = self.prepare(branches(), "aa")
        aid = analyze_anchored(self.db, *binding, anchors=(("ab", 0, 2),))
        row = self.db.connection.execute(
            "SELECT payload FROM requests WHERE id=(SELECT request_ref FROM analyses WHERE id=?)",
            (aid,)).fetchone()
        fixed = json.loads(row[0])
        # Corrupt the encoded anchor tuple into a duplicated one and refresh the
        # request digest so only normalization can catch it.
        payload = load_published_analysis(self.db, aid)["request"]
        payload["request"]["anchors"] = (("ab", 0, 2), ("ab", 0, 2))
        from sequence_lab.delivery.codec import encode_value as enc
        self.db.connection.execute(
            "UPDATE requests SET payload=?,digest=? WHERE id=(SELECT request_ref FROM analyses WHERE id=?)",
            (enc(payload), content_digest(payload), aid))
        with self.assertRaises(ValueError):
            load_published_analysis(self.db, aid)
