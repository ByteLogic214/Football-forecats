"""Tests del motor probabilístico y de valor (sin red)."""
import math

from src.engine import devig_prob, goal_lambdas, kelly_stake, norm
from src.models import TeamRecentStats, TeamSeasonStats
from src.poisson import fair_odds, p_btts, poisson_over, score_matrix


def test_matrix_sums_to_one():
    m = score_matrix(1.4, 1.1)
    assert abs(sum(sum(row) for row in m) - 1.0) < 1e-9


def test_btts_formula():
    m = score_matrix(1.5, 1.5)
    p_h0 = sum(m[0][j] for j in range(len(m)))
    p_a0 = sum(m[i][0] for i in range(len(m)))
    expected = 1 - p_h0 - p_a0 + m[0][0]
    assert abs(p_btts(m) - expected) < 1e-12


def test_poisson_over_known_value():
    # P(X >= 2), X ~ Poisson(2) = 1 - e^-2 * (1 + 2)
    expected = 1 - math.exp(-2) * 3
    assert abs(poisson_over(2.0, 1.5) - expected) < 1e-9
    assert 0.0 < poisson_over(2.0, 1.5) < 1.0


def test_fair_odds():
    assert abs(fair_odds(0.5) - 2.0) < 1e-9


def test_devig_two_way():
    p = devig_prob(2.0, 1.8, "over")
    assert abs(p - (0.5 / (0.5 + 1 / 1.8))) < 1e-9
    assert devig_prob(None, 1.8, "over") is None


def test_kelly_nonnegative_and_capped():
    stake = kelly_stake(0.6, 2.5, 1000.0, 0.25, 0.03)
    assert 0.0 <= stake <= 30.0
    assert kelly_stake(0.6, None, 1000.0, 0.25, 0.03) == 0.0


def test_goal_lambdas_home_boost():
    season = TeamSeasonStats(team_id="t1", played=10, goals_for=20, goals_against=10)
    recent = TeamRecentStats(matches_used=5, goals_for_pg=2.0, goals_against_pg=1.0)
    lh, la = goal_lambdas(season, season, recent, recent, 0.6, 1.12)
    assert lh > la  # la localía debe inflar al local
    assert lh > 0 and la > 0


def test_norm():
    assert norm("Real Madrid CF") == norm("real madrid")
    assert norm("Atlético de Madrid") == "atleticodemadrid"
