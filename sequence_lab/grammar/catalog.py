from dataclasses import dataclass
from types import MappingProxyType
from sequence_lab.grammar.model import GrammarRevision, Rule


@dataclass(frozen=True)
class RuleCatalog:
    by_id: object
    by_lhs: object

    def select_ids(self, rule_ids):
        if not isinstance(rule_ids, (tuple, list)):
            raise ValueError("rule IDs must be a sequence")
        ids = tuple(rule_ids)
        if any(not isinstance(x, str) for x in ids):
            raise ValueError("rule IDs must be strings")
        if len(ids) > 2 or len(set(ids)) != len(ids):
            raise ValueError("select zero to two distinct rules")
        try:
            return tuple(self.by_id[x] for x in ids)
        except KeyError as exc:
            raise ValueError("unknown original rule ID") from exc

    def rules_for(self, lhs):
        return self.by_lhs.get(lhs, ())


def build_catalog(grammar: GrammarRevision):
    by_id, by_lhs = {}, {}
    for rule in grammar.rules:
        if not isinstance(rule, Rule) or not isinstance(rule.rule_id, str):
            raise ValueError("invalid rule")
        if not rule.rule_id or rule.rule_id in by_id:
            raise ValueError("duplicate or empty rule ID")
        if not isinstance(rule.lhs, str):
            raise ValueError("invalid rule lhs")
        by_id[rule.rule_id] = rule
        by_lhs.setdefault(rule.lhs, []).append(rule)
    return RuleCatalog(MappingProxyType(by_id),
                       MappingProxyType({k: tuple(v) for k, v in by_lhs.items()}))
