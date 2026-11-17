from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from sequence_lab.compiler.contributions import select_contributions
from sequence_lab.compiler.unary import apply_closure


@dataclass(frozen=True)
class ConditionalStatistics:
    means: tuple[Fraction, ...]
    covariance: tuple[tuple[Fraction, ...], ...]

    def canonical_record(self):
        return dict(means=self.means, covariance=self.covariance)


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    evidence: Fraction
    rule_ids: tuple[str, ...]
    statistics: ConditionalStatistics | None

    def canonical_record(self):
        return dict(status=self.status, evidence=self.evidence, rule_ids=self.rule_ids,
                    statistics=None if self.statistics is None else
                    self.statistics.canonical_record())

    @classmethod
    def from_record(cls, record):
        if type(record) is not dict or set(record) != {
                "status", "evidence", "rule_ids", "statistics"}:
            raise ValueError("invalid result structure")
        stats = record["statistics"]
        if stats is not None:
            if type(stats) is not dict or set(stats) != {"means", "covariance"}:
                raise ValueError("invalid statistics structure")
            stats = ConditionalStatistics(**stats)
        result = cls(record["status"], record["evidence"], record["rule_ids"], stats)
        result.validate()
        return result

    def validate(self):
        if not isinstance(self.evidence, Fraction) or not 0 <= self.evidence <= 1:
            raise ValueError("invalid evidence")
        if (type(self.rule_ids) is not tuple or len(self.rule_ids) > 2
                or any(type(x) is not str or not x for x in self.rule_ids)
                or len(set(self.rule_ids)) != len(self.rule_ids)):
            raise ValueError("invalid result rule identities")
        if self.evidence == 0:
            if self.status != "impossible" or self.statistics is not None:
                raise ValueError("zero evidence must have no conditional statistics")
            return
        if self.status != "ok" or not isinstance(self.statistics, ConditionalStatistics):
            raise ValueError("positive evidence requires statistics")
        means, covariance = self.statistics.means, self.statistics.covariance
        d = len(self.rule_ids)
        if (type(means) is not tuple or type(covariance) is not tuple
                or len(means) != d or len(covariance) != d
                or any(type(row) is not tuple or len(row) != d for row in covariance)):
            raise ValueError("invalid statistics dimensions")
        if any(not isinstance(x, Fraction) or x < 0 for x in means):
            raise ValueError("invalid means")
        if any(not isinstance(x, Fraction) for row in covariance for x in row):
            raise ValueError("statistics must be exact Fraction")
        for r in range(d):
            if covariance[r][r] < 0:
                raise ValueError("negative variance")
            for s in range(d):
                if covariance[r][s] != covariance[s][r]:
                    raise ValueError("asymmetric covariance")


@dataclass(frozen=True)
class MomentChart:
    evidence: object
    rule_ids: tuple[str, ...]
    first: object
    second: object


def compute_moments(plan, evidence, rule_ids):
    if evidence.plan is not plan:
        raise ValueError("moment/evidence plan mismatch")
    selected = select_contributions(plan, rule_ids)
    d, n = len(selected), len(plan.symbols)
    rewards = {(kind, i): tuple(Fraction(c.application_reward if c.kind == kind and c.edge_index == i else 0)
                                for c in selected)
               for kind, edges in (("emit", plan.emissions), ("unary", plan.unary),
                                   ("binary", plan.binary)) for i in range(len(edges))}
    first, second = {}, {}
    for length in range(1, len(evidence.sequence) + 1):
        for i in range(len(evidence.sequence) - length + 1):
            j = i + length
            b1 = [[Fraction(0) for _ in range(n)] for _ in range(d)]
            b2 = [[[Fraction(0) for _ in range(n)] for _ in range(d)] for _ in range(d)]
            if length == 1:
                for e, edge in enumerate(plan.emissions):
                    if edge.character != evidence.sequence[i]:
                        continue
                    reward = rewards["emit", e]
                    for r in range(d):
                        b1[r][edge.lhs] += edge.weight * reward[r]
                        for s in range(d):
                            b2[r][s][edge.lhs] += edge.weight * reward[r] * reward[s]
            for e, edge in enumerate(plan.binary):
                reward = rewards["binary", e]
                for k in range(i + 1, j):
                    zl = evidence.values[i, k][edge.left]
                    zr = evidence.values[k, j][edge.right]
                    ml = first[i, k]
                    mr = first[k, j]
                    hl = second[i, k]
                    hr = second[k, j]
                    for r in range(d):
                        total_r = ml[r][edge.left] * zr + zl * mr[r][edge.right]
                        b1[r][edge.lhs] += edge.weight * (total_r + reward[r] * zl * zr)
                        for s in range(d):
                            total_s = ml[s][edge.left] * zr + zl * mr[s][edge.right]
                            product = (hl[r][s][edge.left] * zr + zl * hr[r][s][edge.right]
                                       + ml[r][edge.left] * mr[s][edge.right]
                                       + ml[s][edge.left] * mr[r][edge.right]
                                       + reward[r] * total_s + reward[s] * total_r
                                       + reward[r] * reward[s] * zl * zr)
                            b2[r][s][edge.lhs] += edge.weight * product
            z = evidence.values[i, j]
            for e, edge in enumerate(plan.unary):
                reward = rewards["unary", e]
                for r in range(d):
                    b1[r][edge.lhs] += edge.weight * reward[r] * z[edge.child]
            m = tuple(apply_closure(plan.closure, values) for values in b1)
            first[i, j] = m
            for e, edge in enumerate(plan.unary):
                reward = rewards["unary", e]
                for r in range(d):
                    for s in range(d):
                        b2[r][s][edge.lhs] += edge.weight * (
                            reward[r] * m[s][edge.child] + reward[s] * m[r][edge.child]
                            + reward[r] * reward[s] * z[edge.child])
            second[i, j] = tuple(tuple(apply_closure(plan.closure, values) for values in row)
                                  for row in b2)
    return MomentChart(evidence, tuple(rule_ids), MappingProxyType(first),
                       MappingProxyType(second))


def condition_statistics(moments):
    chart = moments.evidence
    z = chart.start_evidence
    if z == 0:
        result = AnalysisResult("impossible", z, moments.rule_ids, None)
    else:
        span = (0, len(chart.sequence))
        start = chart.plan.start_index
        means = tuple(row[start] / z for row in moments.first[span])
        covariance = tuple(tuple(moments.second[span][r][s][start] / z - means[r] * means[s]
                                 for s in range(len(means))) for r in range(len(means)))
        result = AnalysisResult("ok", z, moments.rule_ids,
                                ConditionalStatistics(means, covariance))
    result.validate()
    return result
