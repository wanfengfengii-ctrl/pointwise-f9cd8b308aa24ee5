from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from sequence_lab.compiler.unary import apply_closure


@dataclass(frozen=True)
class EvidenceChart:
    plan: object
    sequence: str
    values: object

    @property
    def start_evidence(self):
        return self.values[(0, len(self.sequence))][self.plan.start_index]


def compute_evidence(plan, sequence):
    plan.check_binding(plan.grammar)
    if not isinstance(sequence, str) or not 1 <= len(sequence) <= 24:
        raise ValueError("sequence length must be 1..24 codepoints")
    n, chart = len(plan.symbols), {}
    for length in range(1, len(sequence) + 1):
        for i in range(len(sequence) - length + 1):
            j = i + length
            base = [Fraction(0) for _ in range(n)]
            if length == 1:
                for edge in plan.emissions:
                    if edge.character == sequence[i]:
                        base[edge.lhs] += edge.weight
            for edge in plan.binary:
                for k in range(i + 1, j):
                    base[edge.lhs] += (edge.weight * chart[i, k][edge.left]
                                       * chart[k, j][edge.right])
            chart[i, j] = apply_closure(plan.closure, base)
    return EvidenceChart(plan, sequence, MappingProxyType(chart))
