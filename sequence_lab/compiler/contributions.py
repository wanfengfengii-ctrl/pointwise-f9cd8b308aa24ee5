from dataclasses import dataclass
from sequence_lab.grammar.catalog import build_catalog


@dataclass(frozen=True)
class RuleContribution:
    rule_id: str
    kind: str
    edge_index: int

    @property
    def application_reward(self):
        return 1


def build_contributions(grammar, emissions, unary, binary):
    contributions = []
    for kind, edges in (("emit", emissions), ("unary", unary), ("binary", binary)):
        contributions.extend(RuleContribution(edge.rule_id, kind, i)
                             for i, edge in enumerate(edges))
    validate_contribution_map(grammar, emissions, unary, binary, tuple(contributions))
    return tuple(contributions)


def validate_contribution_map(grammar, emissions, unary, binary, contributions):
    catalog = build_catalog(grammar)
    groups = {"emit": emissions, "unary": unary, "binary": binary}
    seen, positions = set(), set()
    index = {symbol: i for i, symbol in enumerate(grammar.nonterminals)}
    for contribution in contributions:
        if contribution.rule_id in seen or contribution.rule_id not in catalog.by_id:
            raise ValueError("invalid contribution identity")
        rule = catalog.by_id[contribution.rule_id]
        key = (contribution.kind, contribution.edge_index)
        if contribution.kind not in groups or key in positions:
            raise ValueError("invalid contribution position")
        edges = groups[contribution.kind]
        if type(contribution.edge_index) is not int or not 0 <= contribution.edge_index < len(edges):
            raise ValueError("invalid contribution index")
        edge = edges[contribution.edge_index]
        if (edge.rule_id != rule.rule_id or rule.kind != contribution.kind
                or edge.weight != rule.weight or edge.lhs != index[rule.lhs]):
            raise ValueError("contribution disagrees with original rule")
        target = ((edge.character,) if rule.kind == "emit" else
                  (grammar.nonterminals[edge.child],) if rule.kind == "unary" else
                  (grammar.nonterminals[edge.left], grammar.nonterminals[edge.right]))
        if target != rule.rhs:
            raise ValueError("contribution right-hand side mismatch")
        seen.add(rule.rule_id)
        positions.add(key)
    if seen != set(catalog.by_id) or len(positions) != sum(map(len, groups.values())):
        raise ValueError("incomplete original rule contribution map")
    return True


def select_contributions(plan, rule_ids):
    build_catalog(plan.grammar).select_ids(rule_ids)
    validate_contribution_map(plan.grammar, plan.emissions, plan.unary,
                              plan.binary, plan.contributions)
    directory = {c.rule_id: c for c in plan.contributions}
    return tuple(directory[rule_id] for rule_id in rule_ids)
