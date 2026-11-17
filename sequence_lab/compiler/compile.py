from sequence_lab.grammar.validation import validate_grammar
from sequence_lab.grammar.catalog import build_catalog
from sequence_lab.compiler.plan import CompiledPlan, EmissionEdge, UnaryEdge, BinaryEdge
from sequence_lab.compiler.unary import build_unary_matrix, build_unary_closure
from sequence_lab.compiler.contributions import build_contributions
from sequence_lab.delivery.codec import content_digest


class CompilationError(ValueError):
    pass


def compile_grammar(grammar):
    validate_grammar(grammar)
    catalog = build_catalog(grammar)
    index = {symbol: i for i, symbol in enumerate(grammar.nonterminals)}
    emissions, unary, binary = [], [], []
    for symbol in grammar.nonterminals:
        for rule in catalog.rules_for(symbol):
            lhs = index[rule.lhs]
            if rule.kind == "emit":
                emissions.append(EmissionEdge(rule.rule_id, lhs, rule.rhs[0], rule.weight))
            elif rule.kind == "unary":
                unary.append(UnaryEdge(rule.rule_id, lhs, index[rule.rhs[0]], rule.weight))
            else:
                binary.append(BinaryEdge(rule.rule_id, lhs, index[rule.rhs[0]],
                                         index[rule.rhs[1]], rule.weight))
    emissions, unary, binary = tuple(emissions), tuple(unary), tuple(binary)
    matrix = build_unary_matrix(grammar.nonterminals, unary)
    try:
        closure = build_unary_closure(matrix)
        contributions = build_contributions(grammar, emissions, unary, binary)
    except ValueError as exc:
        raise CompilationError(str(exc)) from exc
    plan = CompiledPlan(grammar, content_digest(grammar.canonical_record()),
                        grammar.nonterminals, emissions, unary, binary,
                        matrix, closure, contributions)
    plan.check_binding(grammar)
    return plan
