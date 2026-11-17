"""Exact joint conditional analysis for original-rule yield-span anchors.

Every chart cell carries, for each anchor mask, the total weight of the finite
parses of that span whose witnessed anchor set is exactly the mask.  A mask bit
is set when the original rule is applied at least once with the anchor's yield
span.  Cells combine child masks by OR; unary closure chains solve one rational
linear system per mask because a witnessing unary application maps a child mask
to ``child | {bit}`` (and repeated applications at the same span are ordinary
same-mask transitions once the bit is present).
"""
from fractions import Fraction

from sequence_lab.analysis.moments import AnalysisResult, ConditionalStatistics
from sequence_lab.compiler.contributions import select_contributions


ZERO = Fraction(0)


def _solve_batch(matrix, vectors):
    """Solve one exact rational system for several right-hand sides at once."""
    n = len(matrix)
    if any(len(row) != n for row in matrix):
        raise ValueError("anchored linear system dimensions disagree")
    if any(len(vector) != n for vector in vectors):
        raise ValueError("anchored right-hand side dimensions disagree")
    if not vectors:
        return ()
    augmented = [[Fraction(x) for x in matrix[row]]
                 + [Fraction(vector[row]) for vector in vectors] for row in range(n)]
    for col in range(n):
        pivot = next((row for row in range(col, n) if augmented[row][col]), None)
        if pivot is None:
            raise ValueError("singular anchored unary system")
        if pivot != col:
            augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [x / scale for x in augmented[col]]
        for row in range(n):
            if row != col:
                factor = augmented[row][col]
                if factor:
                    augmented[row] = [x - factor * y
                                      for x, y in zip(augmented[row], augmented[col])]
    return tuple(tuple(augmented[row][n + col] for row in range(n))
                 for col in range(len(vectors)))


def _rewards(plan, rule_ids):
    selected = select_contributions(plan, rule_ids)
    position = {(c.kind, c.edge_index): r for r, c in enumerate(selected)}
    result = {}
    for kind, edges in (("emit", plan.emissions), ("unary", plan.unary),
                        ("binary", plan.binary)):
        table = []
        for index in range(len(edges)):
            owner = position.get((kind, index))
            table.append(tuple(Fraction(1) if owner == r else ZERO
                               for r in range(len(selected))))
        result[kind] = table
    return result


def compute_anchored_result(plan, sequence, anchors, rule_ids):
    plan.check_binding(plan.grammar)
    if not isinstance(sequence, str) or not 1 <= len(sequence) <= 24:
        raise ValueError("sequence length must be 1..24 codepoints")
    rule_ids = tuple(rule_ids)
    anchors = tuple(anchors)
    reward = _rewards(plan, rule_ids)
    d, n = len(rule_ids), len(plan.symbols)
    start = plan.start_index
    bits = {(rule_id, i, j): 1 << b
            for b, (rule_id, i, j) in enumerate(anchors)}
    masks = 1 << len(anchors)
    full = masks - 1
    evidence_chart, first_chart, second_chart = {}, {}, {}
    for length in range(1, len(sequence) + 1):
        for i in range(len(sequence) - length + 1):
            j = i + length
            b0 = [[ZERO] * n for _ in range(masks)]
            b1 = [[[ZERO] * n for _ in range(d)] for _ in range(masks)]
            b2 = [[[[ZERO] * n for _ in range(d)] for _ in range(d)]
                  for _ in range(masks)]
            if length == 1:
                for e, edge in enumerate(plan.emissions):
                    if edge.character != sequence[i] or not edge.weight:
                        continue
                    mask = bits.get((edge.rule_id, i, j), 0)
                    rw = reward["emit"][e]
                    b0[mask][edge.lhs] += edge.weight
                    for r in range(d):
                        if rw[r]:
                            b1[mask][r][edge.lhs] += edge.weight * rw[r]
                            for s in range(d):
                                if rw[s]:
                                    b2[mask][r][s][edge.lhs] += (
                                        edge.weight * rw[r] * rw[s])
            for e, edge in enumerate(plan.binary):
                weight = edge.weight
                if not weight:
                    continue
                own = bits.get((edge.rule_id, i, j), 0)
                rw = reward["binary"][e]
                left, right = edge.left, edge.right
                for k in range(i + 1, j):
                    ez, er, eh = evidence_chart[i, k], first_chart[i, k], second_chart[i, k]
                    fz, fr, fh = evidence_chart[k, j], first_chart[k, j], second_chart[k, j]
                    for ml in range(masks):
                        zl = ez[ml][left]
                        if not zl:
                            continue
                        ml1, ml2 = er[ml], eh[ml]
                        for mr in range(masks):
                            zr = fz[mr][right]
                            if not zr:
                                continue
                            mask = ml | mr | own
                            product = zl * zr
                            b0[mask][edge.lhs] += weight * product
                            mr1, mr2 = fr[mr], fh[mr]
                            for r in range(d):
                                term = ml1[r][left] * zr + zl * mr1[r][right]
                                if rw[r]:
                                    term += rw[r] * product
                                b1[mask][r][edge.lhs] += weight * term
                                for s in range(d):
                                    value = (ml2[r][s][left] * zr + zl * mr2[r][s][right]
                                             + ml1[r][left] * mr1[s][right]
                                             + ml1[s][left] * mr1[r][right])
                                    if rw[r]:
                                        value += rw[r] * (ml1[s][left] * zr
                                                          + zl * mr1[s][right])
                                    if rw[s]:
                                        value += rw[s] * (ml1[r][left] * zr
                                                          + zl * mr1[r][right])
                                    if rw[r] and rw[s]:
                                        value += rw[r] * rw[s] * product
                                    b2[mask][r][s][edge.lhs] += weight * value
            z_values, first_values, second_values = [], [], []
            for mask in range(masks):
                system = [[Fraction(a == b) for b in range(n)] for a in range(n)]
                same, lower = [], []
                for e, edge in enumerate(plan.unary):
                    weight = edge.weight
                    if not weight:
                        continue
                    own = bits.get((edge.rule_id, i, j), 0)
                    if (own & mask) != own:
                        continue
                    system[edge.lhs][edge.child] -= weight
                    same.append((weight, reward["unary"][e], edge.lhs, edge.child))
                    for child in range(masks):
                        if child != mask and (child | own) == mask:
                            lower.append((weight, reward["unary"][e],
                                          edge.lhs, edge.child, child))
                vector0 = list(b0[mask])
                for weight, _, lhs, child, prior in lower:
                    vector0[lhs] += weight * z_values[prior][child]
                z_vector = _solve_batch(system, [vector0])[0]
                vectors1 = [list(b1[mask][r]) for r in range(d)]
                for weight, rw, lhs, child in same:
                    for r in range(d):
                        if rw[r]:
                            vectors1[r][lhs] += weight * rw[r] * z_vector[child]
                for weight, rw, lhs, child, prior in lower:
                    prior_z = z_values[prior][child]
                    for r in range(d):
                        vectors1[r][lhs] += weight * (
                            first_values[prior][r][child] + rw[r] * prior_z)
                first_vector = _solve_batch(system, vectors1)
                vectors2 = [[list(b2[mask][r][s]) for s in range(d)]
                            for r in range(d)]
                for weight, rw, lhs, child in same:
                    for r in range(d):
                        for s in range(d):
                            vectors2[r][s][lhs] += weight * (
                                rw[r] * first_vector[s][child]
                                + rw[s] * first_vector[r][child]
                                + rw[r] * rw[s] * z_vector[child])
                for weight, rw, lhs, child, prior in lower:
                    prior_z = z_values[prior][child]
                    for r in range(d):
                        for s in range(d):
                            vectors2[r][s][lhs] += weight * (
                                second_values[prior][r][s][child]
                                + rw[r] * first_values[prior][s][child]
                                + rw[s] * first_values[prior][r][child]
                                + rw[r] * rw[s] * prior_z)
                second_vector = _solve_batch(
                    system, [vectors2[r][s] for r in range(d) for s in range(d)])
                z_values.append(tuple(z_vector))
                first_values.append(tuple(tuple(vector) for vector in first_vector))
                second_values.append(tuple(
                    tuple(second_vector[r * d + s] for s in range(d))
                    for r in range(d)))
            evidence_chart[i, j] = tuple(z_values)
            first_chart[i, j] = tuple(first_values)
            second_chart[i, j] = tuple(second_values)
    span = (0, len(sequence))
    evidence = evidence_chart[span][full][start]
    if evidence == 0:
        result = AnalysisResult("impossible", ZERO, rule_ids, None)
    else:
        means = tuple(first_chart[span][full][r][start] / evidence for r in range(d))
        covariance = tuple(
            tuple(second_chart[span][full][r][s][start] / evidence
                  - means[r] * means[s] for s in range(d)) for r in range(d))
        result = AnalysisResult("ok", evidence, rule_ids,
                                ConditionalStatistics(means, covariance))
    result.validate()
    return result
