from dataclasses import dataclass
from fractions import Fraction
from sequence_lab.grammar.model import GrammarRevision
from sequence_lab.delivery.codec import content_digest


@dataclass(frozen=True)
class EmissionEdge:
    rule_id: str
    lhs: int
    character: str
    weight: Fraction


@dataclass(frozen=True)
class UnaryEdge:
    rule_id: str
    lhs: int
    child: int
    weight: Fraction


@dataclass(frozen=True)
class BinaryEdge:
    rule_id: str
    lhs: int
    left: int
    right: int
    weight: Fraction


@dataclass(frozen=True)
class CompiledPlan:
    grammar: GrammarRevision
    grammar_digest: str
    symbols: tuple[str, ...]
    emissions: tuple[EmissionEdge, ...]
    unary: tuple[UnaryEdge, ...]
    binary: tuple[BinaryEdge, ...]
    unary_matrix: tuple[tuple[Fraction, ...], ...]
    closure: tuple[tuple[Fraction, ...], ...]
    contributions: tuple

    @property
    def start_index(self):
        return self.symbols.index(self.grammar.start)

    def check_binding(self, grammar):
        if (self.grammar_digest != content_digest(grammar.canonical_record())
                or self.symbols != grammar.nonterminals):
            raise ValueError("compiled plan grammar binding mismatch")
        return True
