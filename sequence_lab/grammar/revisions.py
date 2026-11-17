from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.grammar.validation import validate_grammar
from sequence_lab.delivery.codec import encode_value, decode_value, content_digest


class GrammarRevisionConflict(ValueError):
    pass


def save_grammar(db, grammar):
    validate_grammar(grammar)
    record = grammar.canonical_record()
    payload, digest = encode_value(record), content_digest(record)
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT id,payload FROM grammars WHERE grammar_id=? AND revision=?",
            (grammar.grammar_id, grammar.revision)).fetchone()
        if row:
            if row["payload"] != payload:
                raise GrammarRevisionConflict("same grammar revision has different content")
            return row["id"]
        return connection.execute(
            "INSERT INTO grammars(grammar_id,revision,payload,digest) VALUES(?,?,?,?)",
            (grammar.grammar_id, grammar.revision, payload, digest)).lastrowid


def load_grammar_revision(db, grammar_ref):
    row = db.connection.execute("SELECT * FROM grammars WHERE id=?", (grammar_ref,)).fetchone()
    if row is None:
        raise KeyError("unknown grammar revision")
    record = decode_value(row["payload"])
    if content_digest(record) != row["digest"]:
        raise ValueError("grammar fingerprint mismatch")
    grammar = GrammarRevision.from_record(record)
    if grammar.grammar_id != row["grammar_id"] or grammar.revision != row["revision"]:
        raise ValueError("grammar identity mismatch")
    return validate_grammar(grammar)
