from fractions import Fraction
from itertools import combinations
from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.grammar.catalog import build_catalog


class GrammarValidationError(ValueError):
    pass


def _determinant(matrix):
    a = [list(row) for row in matrix]
    determinant = Fraction(1)
    for col in range(len(a)):
        pivot = next((i for i in range(col, len(a)) if a[i][col]), None)
        if pivot is None:
            return Fraction(0)
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            determinant = -determinant
        scale = a[col][col]
        determinant *= scale
        for row in range(col + 1, len(a)):
            factor = a[row][col] / scale
            for j in range(col + 1, len(a)):
                a[row][j] -= factor * a[col][j]
    return determinant


def check_unary_support(grammar):
    n = len(grammar.nonterminals)
    index = {name: i for i, name in enumerate(grammar.nonterminals)}
    matrix = [[Fraction(19, 20) if i == j else Fraction(0)
               for j in range(n)] for i in range(n)]
    for rule in grammar.rules:
        if rule.kind == "unary":
            matrix[index[rule.lhs]][index[rule.rhs[0]]] -= rule.weight
    for size in range(1, n + 1):
        for subset in combinations(range(n), size):
            minor = [[matrix[i][j] for j in subset] for i in subset]
            if _determinant(minor) < 0:
                raise GrammarValidationError("unary spectral radius exceeds 19/20")
    return True


def validate_grammar(grammar):
    if not isinstance(grammar, GrammarRevision):
        raise GrammarValidationError("expected GrammarRevision")
    if not isinstance(grammar.grammar_id, str) or not grammar.grammar_id:
        raise GrammarValidationError("empty grammar identity")
    if type(grammar.revision) is not int or grammar.revision < 1:
        raise GrammarValidationError("revision must be positive integer")
    nts, alphabet = grammar.nonterminals, grammar.alphabet
    if not isinstance(nts, tuple) or not 1 <= len(nts) <= 8:
        raise GrammarValidationError("one to eight nonterminals required")
    if any(not isinstance(x, str) or not x for x in nts):
        raise GrammarValidationError("invalid nonterminal")
    if len(set(nts)) != len(nts) or grammar.start not in nts:
        raise GrammarValidationError("duplicate symbols or unknown start")
    if not isinstance(alphabet, tuple) or any(
            not isinstance(c, str) or len(c) != 1 for c in alphabet):
        raise GrammarValidationError("alphabet entries must be Unicode codepoints")
    if len(set(alphabet)) != len(alphabet):
        raise GrammarValidationError("duplicate alphabet")
    if not isinstance(grammar.rules, tuple) or not 1 <= len(grammar.rules) <= 16:
        raise GrammarValidationError("one to sixteen rules required")
    try:
        catalog = build_catalog(grammar)
    except ValueError as exc:
        raise GrammarValidationError(str(exc)) from exc
    for rule in grammar.rules:
        if rule.lhs not in nts or rule.kind not in ("emit", "unary", "binary"):
            raise GrammarValidationError("unknown rule symbol or kind")
        if not isinstance(rule.weight, Fraction) or rule.weight < 0:
            raise GrammarValidationError("weights must be nonnegative Fraction")
        arity = 2 if rule.kind == "binary" else 1
        if not isinstance(rule.rhs, tuple) or len(rule.rhs) != arity:
            raise GrammarValidationError("invalid arity; no empty productions")
        domain = alphabet if rule.kind == "emit" else nts
        if any(not isinstance(x, str) or x not in domain for x in rule.rhs):
            raise GrammarValidationError("unknown right-hand symbol")
    for nt in nts:
        if sum((r.weight for r in catalog.rules_for(nt)), Fraction(0)) != 1:
            raise GrammarValidationError("each nonterminal must have total weight one")
    check_unary_support(grammar)
    return grammar
