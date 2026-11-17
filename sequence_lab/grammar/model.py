from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Rule:
    rule_id: str
    lhs: str
    kind: str
    rhs: tuple[str, ...]
    weight: Fraction

    def __post_init__(self):
        if isinstance(self.rhs, (list, tuple)):
            object.__setattr__(self, "rhs", tuple(self.rhs))

    def canonical_record(self):
        return dict(rule_id=self.rule_id, lhs=self.lhs, kind=self.kind,
                    rhs=self.rhs, weight=self.weight)


@dataclass(frozen=True)
class GrammarRevision:
    grammar_id: str
    revision: int
    start: str
    nonterminals: tuple[str, ...]
    alphabet: tuple[str, ...]
    rules: tuple[Rule, ...]

    def __post_init__(self):
        for field in ("nonterminals", "alphabet", "rules"):
            value = getattr(self, field)
            if isinstance(value, (list, tuple)):
                object.__setattr__(self, field, tuple(value))

    def canonical_record(self):
        return dict(grammar_id=self.grammar_id, revision=self.revision,
                    start=self.start, nonterminals=self.nonterminals,
                    alphabet=self.alphabet,
                    rules=tuple(r.canonical_record() for r in self.rules))

    @classmethod
    def from_record(cls, record):
        values = dict(record)
        values["rules"] = tuple(Rule(**r) for r in values["rules"])
        return cls(**values)
