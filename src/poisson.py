"""Motor probabilístico: matriz de marcadores con Poisson independiente.

Extensión natural: Dixon-Coles (ajuste de goles bajos + correlación temporal).
"""
from __future__ import annotations

import math

MAX_GOALS = 10


def pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def score_matrix(lam_home: float, lam_away: float) -> list[list[float]]:
    """m[i][j] = P(marcador exacto i-j), normalizada a 1."""
    ph = [pmf(i, lam_home) for i in range(MAX_GOALS + 1)]
    pa = [pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
    m = [[ph[i] * pa[j] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    total = sum(sum(row) for row in m)
    return [[c / total for c in row] for row in m]


def p_home_win(m: list[list[float]]) -> float:
    return sum(m[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i > j)


def p_draw(m: list[list[float]]) -> float:
    return sum(m[i][i] for i in range(MAX_GOALS + 1))


def p_away_win(m: list[list[float]]) -> float:
    return sum(m[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i < j)


def p_over(m: list[list[float]], line: float) -> float:
    """P(total goles > line). Para línea 2.5 => totales >= 3."""
    return sum(m[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i + j > line)


def p_btts(m: list[list[float]]) -> float:
    """P(ambos anotan) = 1 - P(local 0) - P(visitante 0) + P(0-0)."""
    p_h0 = sum(m[0][j] for j in range(MAX_GOALS + 1))
    p_a0 = sum(m[i][0] for i in range(MAX_GOALS + 1))
    return 1.0 - p_h0 - p_a0 + m[0][0]


def poisson_over(lam: float, line: float) -> float:
    """P(X > line) para X ~ Poisson(lam). Sirve para córners y remates al arco."""
    k_needed = int(math.floor(line)) + 1
    return 1.0 - sum(pmf(k, lam) for k in range(k_needed))


def fair_odds(prob: float) -> float:
    return round(1.0 / prob, 3) if prob > 0 else float("inf")
