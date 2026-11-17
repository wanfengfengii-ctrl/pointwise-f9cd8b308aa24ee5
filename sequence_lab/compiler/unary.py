from fractions import Fraction


def solve_fraction_system(matrix, rhs):
    n = len(matrix)
    if len(rhs) != n or any(len(row) != n for row in matrix):
        raise ValueError("linear system dimensions disagree")
    a = [[Fraction(x) for x in row] + [Fraction(rhs[i])]
         for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = next((i for i in range(col, n) if a[i][col]), None)
        if pivot is None:
            raise ValueError("singular rational system")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [x / scale for x in a[col]]
        for row in range(n):
            if row != col:
                factor = a[row][col]
                a[row] = [x - factor * y for x, y in zip(a[row], a[col])]
    return tuple(row[-1] for row in a)


def build_unary_matrix(symbols, edges):
    n = len(symbols)
    matrix = [[Fraction(0) for _ in range(n)] for _ in range(n)]
    for edge in edges:
        if not 0 <= edge.lhs < n or not 0 <= edge.child < n:
            raise ValueError("unary endpoint outside symbol index")
        matrix[edge.lhs][edge.child] += edge.weight
    return tuple(tuple(row) for row in matrix)


def build_unary_closure(matrix):
    n = len(matrix)
    system = [[Fraction(i == j) - matrix[i][j] for j in range(n)] for i in range(n)]
    columns = [solve_fraction_system(system, [Fraction(i == j) for i in range(n)])
               for j in range(n)]
    return tuple(tuple(columns[j][i] for j in range(n)) for i in range(n))


def apply_closure(closure, values):
    if len(closure) != len(values) or any(len(row) != len(values) for row in closure):
        raise ValueError("closure dimensions disagree")
    return tuple(sum((a * b for a, b in zip(row, values)), Fraction(0)) for row in closure)
