import json
import sys
import tempfile
from pathlib import Path
from fractions import Fraction as F
from tests.helpers import LabCase, grammar, emit, loop, parallel, branches
from sequence_lab.delivery.database import open_database
from sequence_lab.delivery.schema import ensure_schema, UnsupportedSchemaVersion
from sequence_lab.delivery.codec import encode_value, decode_value, content_digest, CodecError
from sequence_lab.delivery.publish import load_published_analysis
from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.grammar.revisions import save_grammar
from sequence_lab.cohort.records import SequenceUpdate as U
from sequence_lab.cohort.revisions import apply_sequences, load_current_sources
from sequence_lab.cohort.snapshots import freeze_cohort
from sequence_lab.analysis.execute import analyze_sequence
from sequence_lab.reporting.reports import create_report, ReportCreationError
from sequence_lab.reporting.read import read_report, ReportNotFound
from sequence_lab.reporting.provenance import ProvenanceError
from sequence_lab.reporting.export import (
    build_reproduction_bundle, export_report, load_reproduction_bundle, ReportExportError)


class TestDelivery(LabCase):
    def test_publish_retry_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "lab.sqlite", Path(directory) / "report.json"
            with open_database(path) as db:
                ref = save_grammar(db, parallel())
                apply_sequences(db, [U("x", 1, "a")])
                cohort = freeze_cohort(db, ["x"])
                for stage in ("after_request", "after_result", "before_commit"):
                    def fail(actual, target=stage):
                        if actual == target:
                            raise RuntimeError("injected publication failure")
                    with self.assertRaises(RuntimeError):
                        analyze_sequence(db, ref, cohort, "x", ("p", "q"), fault=fail)
                    for table in ("requests", "analyses", "reports"):
                        self.assertEqual(db.connection.execute(
                            "SELECT count(*) FROM " + table).fetchone()[0], 0)
                    with self.assertRaises(ReportCreationError):
                        create_report(db, 1)
                aid = analyze_sequence(db, ref, cohort, "x", ("p", "q"))
                rid = create_report(db, aid)
                original = read_report(db, rid).canonical_record()
                bundle = export_report(db, rid, output)
                apply_sequences(db, [U("x", 2, "b")])
                new_cohort = freeze_cohort(db, ["x"])
                new_aid = analyze_sequence(db, ref, new_cohort, "x", ("p", "q"))
                self.assertEqual(load_published_analysis(db, new_aid)["result"]["status"],
                                 "impossible")
                save_grammar(db, loop(F(1, 3), revision=2))
            with open_database(path) as db:
                calls = []
                def guard(frame, event, arg):
                    if event == "call" and frame.f_code.co_name in {
                            "analyze_sequence", "compile_grammar", "compute_evidence", "compute_moments"}:
                        calls.append(frame.f_code.co_name)
                        raise AssertionError("read attempted inference")
                previous = sys.getprofile()
                sys.setprofile(guard)
                try:
                    self.assertEqual(read_report(db, rid).canonical_record(), original)
                    self.assertEqual(export_report(db, rid, output), bundle)
                    self.assertEqual(load_reproduction_bundle(output), bundle)
                finally:
                    sys.setprofile(previous)
                self.assertEqual(calls, [])
                self.assertEqual(bundle["report"]["parents"]["member"]["sequence"], "a")

    def test_publication_atomicity_and_report_admission(self):
        binding = self.prepare(loop())
        with self.assertRaises(ReportCreationError):
            create_report(self.db, 999)
        with self.assertRaises(ReportNotFound):
            read_report(self.db, 999)
        for stage in ("after_request", "after_result", "before_commit"):
            def fail(actual, target=stage):
                if actual == target:
                    raise RuntimeError(target)
            with self.assertRaises(RuntimeError):
                analyze_sequence(self.db, *binding, ("loop",), fault=fail)
            for table in ("requests", "analyses", "reports"):
                self.assertEqual(self.db.connection.execute(
                    "SELECT count(*) FROM " + table).fetchone()[0], 0)
            with self.assertRaises(ReportCreationError):
                create_report(self.db, 1)
        aid = analyze_sequence(self.db, *binding, ("loop",))
        self.assertEqual(read_report(self.db, create_report(self.db, aid))
                         .result["statistics"]["covariance"], ((F(2),),))

    def test_initialization_preserves_user_data(self):
        from samples import seed_demo
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lab.sqlite"
            with open_database(path) as db:
                ref = seed_demo(db)
                cohort = freeze_cohort(db, ["sample_01"])
                aid = analyze_sequence(db, ref, cohort, "sample_01", ("p", "q"))
                rid = create_report(db, aid)
                fixed = read_report(db, rid).canonical_record()
                apply_sequences(db, [U("sample_01", 2, "b")])
                ensure_schema(db.connection)
                self.assertEqual(seed_demo(db), ref)
                counts = tuple(db.connection.execute(
                    "SELECT count(*) FROM " + table).fetchone()[0]
                    for table in ("grammars", "sources", "cohorts", "requests", "analyses", "reports"))
            with open_database(path) as db:
                self.assertEqual(read_report(db, rid).canonical_record(), fixed)
                self.assertEqual(load_current_sources(db)["sample_01"].sequence, "b")
                self.assertEqual(tuple(db.connection.execute(
                    "SELECT count(*) FROM " + table).fetchone()[0]
                    for table in ("grammars", "sources", "cohorts", "requests", "analyses", "reports")),
                    counts)
            with open_database() as db:
                db.connection.execute("PRAGMA user_version=99")
                with self.assertRaises(UnsupportedSchemaVersion):
                    ensure_schema(db.connection)
                self.assertEqual(db.connection.execute("PRAGMA user_version").fetchone()[0], 99)
        with open_database() as db:
            seed_demo(db)
            with self.assertRaises(ValueError):
                apply_sequences(db, [U("sample_01", 1, "user_change")])
        with open_database() as db:
            db.connection.execute("DROP TABLE reports")
            ensure_schema(db.connection)
            self.assertEqual(db.connection.execute("SELECT count(*) FROM reports").fetchone()[0], 0)

    def test_exact_roundtrip_and_reproduction(self):
        cases = [(grammar([emit("a", char="a", weight=F(1, 3)),
                           emit("b", char="b", weight=F(2, 3))], name="third"), "a", ("a",)),
                 (branches(), "aa", ("ab", "ba")),
                 (grammar([emit()], name="empty"), "a", ()),
                 (grammar([emit()], name="impossible"), "b", ("emit",))]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lab.sqlite"
            output = Path(directory) / "bundle.json"
            saved = []
            with open_database(path) as db:
                for index, (value, sequence, ids) in enumerate(cases):
                    ref = save_grammar(db, value)
                    source = "x" + str(index)
                    apply_sequences(db, [U(source, 1, sequence)])
                    cohort = freeze_cohort(db, [source])
                    aid = analyze_sequence(db, ref, cohort, source, ids)
                    result = load_published_analysis(db, aid)["result"]
                    saved.append((create_report(db, aid), result))
            with open_database(path) as db:
                for rid, result in saved:
                    report = read_report(db, rid)
                    self.assertEqual(report.result, result)
                    self.assertIsInstance(report.result["evidence"], F)
                    bundle = export_report(db, rid, output)
                    self.assertEqual(load_reproduction_bundle(output), bundle)
                    with open_database() as replay:
                        parents = bundle["report"]["parents"]
                        ref = save_grammar(replay, GrammarRevision.from_record(parents["grammar"]))
                        apply_sequences(replay, [U(**m) for m in parents["cohort"]])
                        cohort = freeze_cohort(replay, [m["source_id"] for m in parents["cohort"]])
                        aid = analyze_sequence(replay, ref, cohort, parents["member"]["source_id"],
                                               report.request["rule_ids"])
                        self.assertEqual(load_published_analysis(replay, aid)["result"], result)
                self.assertEqual(saved[0][1]["evidence"], F(1, 3))
                self.assertEqual(saved[1][1]["statistics"]["covariance"][0][1], F(-1, 4))
                self.assertEqual(saved[2][1]["statistics"], dict(means=(), covariance=()))
                self.assertIsNone(saved[3][1]["statistics"])

    def test_codec_rejects_invalid_values(self):
        values = dict(evidence=F(1, 3), covariance=((F(-1, 4),),),
                      empty=(), impossible=None, text="é🙂", integer=3, flag=True)
        self.assertEqual(decode_value(encode_value(values)), values)
        nodes = [["fraction", 1, 0], ["fraction", 2, 4], ["fraction", True, 1],
                 ["fraction", 1, -3], ["unknown", 1], ["fraction", 1],
                 ["dict", [["x", ["null"]], ["x", ["null"]]]], ["int", 1.2]]
        for node in nodes:
            with self.assertRaises(CodecError):
                decode_value(json.dumps(dict(version=1, value=node)))
        for text in ('{}', '{"version":2,"value":["null"]}',
                     '{"version":true,"value":["null"]}',
                     '{"version":1,"version":1,"value":["null"]}'):
            with self.assertRaises(CodecError):
                decode_value(text)
        with self.assertRaises(CodecError):
            encode_value(1.0)

    def test_return_values_are_independent(self):
        binding = self.prepare(parallel())
        aid = analyze_sequence(self.db, *binding, ("q", "p"))
        rid = create_report(self.db, aid)
        report = read_report(self.db, rid)
        expected = report.canonical_record()
        report.result["evidence"] = F(0)
        report.parents["member"]["sequence"] = "b"
        report.request["rule_ids"] = ()
        again = read_report(self.db, rid)
        self.assertEqual(again.result["evidence"], F(1))
        self.assertEqual(again.parents["member"]["sequence"], "a")
        self.assertEqual(again.request["rule_ids"], ("q", "p"))
        published = load_published_analysis(self.db, aid)
        published["result"]["statistics"]["means"] = ()
        self.assertEqual(load_published_analysis(self.db, aid)["result"]["statistics"]["means"],
                         (F(1, 2), F(1, 2)))
        self.assertNotEqual(again.canonical_record(), expected)

    def test_provenance_rejection(self):
        for damage in ("missing", "crossed", "content"):
            with self.subTest(damage=damage), open_database() as db:
                ref = save_grammar(db, loop())
                apply_sequences(db, [U("x", 1, "a")])
                cohort = freeze_cohort(db, ["x"])
                aid = analyze_sequence(db, ref, cohort, "x", ("loop",))
                rid = create_report(db, aid)
                if damage == "missing":
                    db.connection.execute("PRAGMA foreign_keys=OFF")
                    db.connection.execute("DELETE FROM grammars WHERE id=?", (ref,))
                elif damage == "crossed":
                    other = analyze_sequence(db, ref, cohort, "x", ())
                    db.connection.execute("UPDATE reports SET analysis_ref=? WHERE id=?", (other, rid))
                else:
                    row = db.connection.execute("SELECT payload FROM cohorts WHERE id=?", (cohort,)).fetchone()
                    payload = decode_value(row[0])
                    payload[0]["sequence"] = "b"
                    db.connection.execute("UPDATE cohorts SET payload=? WHERE id=?",
                                          (encode_value(payload), cohort))
                with self.assertRaises(ProvenanceError):
                    read_report(db, rid)
                with self.assertRaises(ProvenanceError):
                    build_reproduction_bundle(db, rid)
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "rejected.json"
                    with self.assertRaises(ProvenanceError):
                        export_report(db, rid, target)
                    self.assertFalse(target.exists())

    def test_export_atomicity(self):
        binding = self.prepare(parallel())
        aid = analyze_sequence(self.db, *binding, ("p", "q"))
        rid = create_report(self.db, aid)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            for existing in (False, True):
                for stage in ("during_write", "before_replace"):
                    if existing:
                        target.write_bytes(b"prior delivery")
                    else:
                        target.unlink(missing_ok=True)
                    def fail(actual, selected=stage):
                        if actual == selected:
                            raise OSError("injected export failure")
                    with self.assertRaises(ReportExportError):
                        export_report(self.db, rid, target, fault=fail)
                    if existing:
                        self.assertEqual(target.read_bytes(), b"prior delivery")
                    else:
                        self.assertFalse(target.exists())
                    self.assertEqual(list(Path(directory).glob(".sequence-export-*")), [])
            # A real filesystem replace error also leaves no temporary package.
            blocked = Path(directory) / "directory"
            blocked.mkdir()
            with self.assertRaises(ReportExportError):
                export_report(self.db, rid, blocked)
            self.assertTrue(blocked.is_dir())
            self.assertEqual(list(Path(directory).glob(".sequence-export-*")), [])
            bundle = export_report(self.db, rid, target)
            self.assertEqual(load_reproduction_bundle(target), bundle)
            bundle["report"]["parents"]["member"]["sequence"] = "b"
            target.write_text(encode_value(bundle), encoding="utf-8")
            with self.assertRaises(ReportExportError):
                load_reproduction_bundle(target)
