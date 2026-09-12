"""Motor del sistema: lambdas, mercados, detección de valor y ranking de picks.

Prioridades del usuario:
  1) Remates (totales y al arco, por equipo y del partido)
  2) Córners (por equipo y del partido)
  3) Ambos anotan (BTTS)
  4) Más/Menos goles del partido
  5) Goles por equipo (team totals)
  6) 1X2
"""
from __future__ import annotations

import math
import re
import unicodedata

from .config import Settings
from .models import Candidate, MatchOdds, TeamRecentStats, TeamSeasonStats
from .poisson import (
    fair_odds,
    p_away_win,
    p_btts,
    p_draw,
    p_home_win,
    p_over,
    pmf,
    poisson_over,
    score_matrix,
)

PRIORITY = {
    "shots_on_target": 1,
    "corners": 2,
    "btts": 3,
    "totals": 4,
    "team_totals": 5,
    "match_odds": 6,
}

LEAGUE_AVG_GOALS = 1.30  # goles por equipo y partido (referencia neutral)


# ---------------------------------------------------------------- normalización
def norm(name: str) -> str:
    """Normaliza nombres de equipos para cruzar TheStatsAPI <-> TheOddsAPI."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"\b(fc|cf|sc|ac|cd|ud|real|club|deportivo)\b", " ", name.lower())
    return re.sub(r"[^a-z0-9]+", "", name)


# ---------------------------------------------------------------- modelo
def goal_lambdas(home: TeamSeasonStats, away: TeamSeasonStats,
                 rh: TeamRecentStats, ra: TeamRecentStats,
                 form_weight: float, home_boost: float) -> tuple[float, float]:
    """Goles esperados de cada equipo: fuerza ofensiva propia x debilidad defensiva rival."""

    def rates(season: TeamSeasonStats, recent: TeamRecentStats) -> tuple[float, float]:
        if season.played > 0:
            s_gf = season.goals_for / season.played
            s_ga = season.goals_against / season.played
        else:
            s_gf = s_ga = LEAGUE_AVG_GOALS
        gf = form_weight * recent.goals_for_pg + (1 - form_weight) * s_gf
        ga = form_weight * recent.goals_against_pg + (1 - form_weight) * s_ga
        return max(gf, 0.15), max(ga, 0.15)

    h_gf, h_ga = rates(home, rh)
    a_gf, a_ga = rates(away, ra)
    lam_home = h_gf * (a_ga / LEAGUE_AVG_GOALS) * home_boost
    lam_away = a_gf * (h_ga / LEAGUE_AVG_GOALS) / home_boost
    return round(lam_home, 3), round(lam_away, 3)


def blend_avg(own_for: float, opp_against: float) -> float:
    """Lambda de un conteo (remates/SOT/córners): mezcla producción propia y concesión rival."""
    return max(0.5 * own_for + 0.5 * opp_against, 0.1)


# ---------------------------------------------------------------- valor / staking
def devig_prob(over_odds: float | None, under_odds: float | None, side: str) -> float | None:
    """Probabilidad implícita sin margen a partir del par over/under."""
    if not over_odds or not under_odds:
        return None
    io, iu = 1.0 / over_odds, 1.0 / under_odds
    return io / (io + iu) if side == "over" else iu / (io + iu)


def kelly_stake(prob: float, odds_price: float | None, bankroll: float,
                fraction: float, cap: float) -> float:
    """Stake en unidades monetarias: Kelly fraccionado, limitado por cap de banca."""
    if not odds_price or odds_price <= 1.0:
        return 0.0
    b = odds_price - 1.0
    f = max((prob * b - (1 - prob)) / b, 0.0)
    return round(min(bankroll * f * fraction, bankroll * cap), 2)


def confidence(prob: float, edge: float | None, quality: float) -> float:
    e = 0.0 if edge is None else max(min(edge / 0.15, 1.0), 0.0)
    return round(0.55 * prob + 0.35 * e + 0.10 * quality, 4)


# ---------------------------------------------------------------- cuotas
def normalize_odds_event(ev: dict, home_name: str, away_name: str) -> MatchOdds:
    """Evento TheOddsAPI -> MatchOdds normalizado (mejor precio por lado)."""
    hn, an = norm(home_name), norm(away_name)
    mo = MatchOdds(sources=["theoddsapi"])

    def keep(store: dict, key: str, price) -> None:
        if price and (store.get(key) is None or price > store[key]):
            store[key] = price

    for bk in ev.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            key = mkt.get("key")
            for out in mkt.get("outcomes", []):
                price = out.get("price")
                if not price:
                    continue
                if key == "h2h":
                    n = norm(out.get("name", ""))
                    if n == hn:
                        keep(mo.match_odds, "home", price)
                    elif n == an:
                        keep(mo.match_odds, "away", price)
                    else:  # "Draw" / "Tie" / "Empate"
                        keep(mo.match_odds, "draw", price)
                elif key == "btts":
                    side = out.get("name", "").lower()
                    if side in ("yes", "si", "sí"):
                        keep(mo.btts, "yes", price)
                    elif side == "no":
                        keep(mo.btts, "no", price)
                elif key == "totals":
                    point = out.get("point")
                    side = (out.get("description") or out.get("name") or "").lower()
                    if point is None:
                        continue
                    tgt = mo.total_goals.setdefault(str(point), {})
                    if "over" in side:
                        keep(tgt, "over", price)
                    elif "under" in side:
                        keep(tgt, "under", price)
                elif key == "team_totals":
                    point = out.get("point")
                    side = (out.get("description") or "").lower()
                    if point is None:
                        continue
                    tgt = mo.team_totals.setdefault(str(point), {}).setdefault(norm(out.get("name", "")), {})
                    if "over" in side:
                        keep(tgt, "over", price)
                    elif "under" in side:
                        keep(tgt, "under", price)
    return mo


def merge_odds(primary: MatchOdds, secondary: MatchOdds) -> MatchOdds:
    """Fusiona dos MatchOdds quedándose con el mejor precio por lado."""
    for side in ("home", "draw", "away"):
        p = secondary.match_odds.get(side)
        if p and (not primary.match_odds.get(side) or p > primary.match_odds[side]):
            primary.match_odds[side] = p
    for side, p in secondary.btts.items():
        if p and (not primary.btts.get(side) or p > primary.btts[side]):
            primary.btts[side] = p

    def merge_lines(dst: dict, src: dict) -> None:
        for line, sides in src.items():
            t = dst.setdefault(line, {})
            for side, price in sides.items():
                if price and (not t.get(side) or price > t[side]):
                    t[side] = price

    merge_lines(primary.total_goals, secondary.total_goals)
    merge_lines(primary.match_corners, secondary.match_corners)
    for line, teams in secondary.team_totals.items():
        for tn, sides in teams.items():
            t = primary.team_totals.setdefault(line, {}).setdefault(tn, {})
            for side, price in sides.items():
                if price and (not t.get(side) or price > t[side]):
                    t[side] = price
    for s in secondary.sources:
        if s not in primary.sources:
            primary.sources.append(s)
    return primary


def parse_stats_odds(raw: dict) -> MatchOdds:
    """Cuotas TheStatsAPI del partido -> MatchOdds normalizado."""
    mo = MatchOdds(sources=["thestatsapi"])

    def keep(store: dict, key: str, raw_value) -> None:
        try:
            price = float(raw_value)
        except (TypeError, ValueError):
            return
        if store.get(key) is None or price > store[key]:
            store[key] = price

    for bk in raw.get("bookmakers", []) or []:
        mk = bk.get("markets", {}) or {}
        mo_ = mk.get("match_odds") or {}
        for side in ("home", "draw", "away"):
            keep(mo.match_odds, side, (mo_.get(side) or {}).get("last_seen"))
        btts = mk.get("btts") or {}
        for side in ("yes", "no"):
            keep(mo.btts, side, (btts.get(side) or {}).get("last_seen"))
        for market_key, target in (("total_goals", mo.total_goals), ("match_corners", mo.match_corners)):
            for line, ou in (mk.get(market_key) or {}).items():
                tgt = target.setdefault(str(line), {})
                for side in ("over", "under"):
                    keep(tgt, side, (ou.get(side) or {}).get("last_seen"))
    return mo


# ---------------------------------------------------------------- candidatos
def build_candidates(home_name: str, away_name: str, hn: str, an: str,
                     odds: MatchOdds, lam_h: float, lam_a: float,
                     rh: TeamRecentStats, ra: TeamRecentStats,
                     settings: Settings) -> tuple[list[Candidate], list[Candidate]]:
    """Genera candidatos de valor (con cuota) y de seguimiento (modelo sin cuota)."""
    sot_h = blend_avg(rh.sot_for_pg, ra.sot_against_pg)
    sot_a = blend_avg(ra.sot_for_pg, rh.sot_against_pg)
    sh_h = blend_avg(rh.shots_for_pg, ra.shots_against_pg)
    sh_a = blend_avg(ra.shots_for_pg, rh.shots_against_pg)
    cor_h = blend_avg(rh.corners_for_pg, ra.corners_against_pg)
    cor_a = blend_avg(ra.corners_for_pg, rh.corners_against_pg)
    quality = min(1.0, min(rh.matches_used, ra.matches_used) / max(settings.sot_lookback, 1))

    matrix = score_matrix(lam_h, lam_a)
    value: list[Candidate] = []
    tracked: list[Candidate] = []

    def emit(bucket: list, market: str, selection: str, line, prob: float,
             price, implied, priority: int) -> None:
        edge = round(prob - implied, 4) if implied is not None else None
        stake = kelly_stake(prob, price, settings.bankroll,
                            settings.kelly_fraction, settings.max_stake_pct) if price else 0.0
        bucket.append(Candidate(
            market=market, selection=selection, line=line,
            model_prob=round(prob, 4), odds=price,
            fair_odds=fair_odds(prob), edge=edge, priority=priority,
            confidence=confidence(prob, edge, quality),
            stake_pct=stake, has_odds=price is not None,
        ))

    # 1) REMATES (prioridad del sistema; casi sin cuotas en agregadores -> seguimiento)
    for line in (1.5, 2.5, 3.5, 4.5):
        p = poisson_over(sot_h, line)
        if p >= settings.min_prob:
            emit(tracked, "shots_on_target", f"{home_name} remates al arco +{line}", line, p, None, None, 1)
        p = poisson_over(sot_a, line)
        if p >= settings.min_prob:
            emit(tracked, "shots_on_target", f"{away_name} remates al arco +{line}", line, p, None, None, 1)
    for line in (8.5, 9.5, 10.5):
        p = poisson_over(sot_h + sot_a, line)
        if p >= settings.min_prob:
            emit(tracked, "shots_on_target", f"Total remates al arco partido +{line}", line, p, None, None, 1)
    for line in (22.5, 25.5):
        p = poisson_over(sh_h + sh_a, line)
        if p >= settings.min_prob:
            emit(tracked, "shots_on_target", f"Total remates partido +{line}", line, p, None, None, 1)

    # 2) CÓRNERS (TheStatsAPI sí publica match_corners)
    if odds.match_corners:
        for line, sides in odds.match_corners.items():
            try:
                L = float(line)
            except ValueError:
                continue
            lam_c = cor_h + cor_a
            po_, pu_ = sides.get("over"), sides.get("under")
            imp_o = devig_prob(po_, pu_, "over")
            imp_u = devig_prob(po_, pu_, "under")
            p_o = poisson_over(lam_c, L)
            if po_ and imp_o is not None and (p_o - imp_o) >= settings.min_edge and p_o >= settings.min_prob:
                emit(value, "corners", f"Córners partido +{L}", L, p_o, po_, imp_o, 2)
            p_u = 1 - p_o
            if pu_ and imp_u is not None and (p_u - imp_u) >= settings.min_edge and p_u >= settings.min_prob:
                emit(value, "corners", f"Córners partido -{L}", L, p_u, pu_, imp_u, 2)
    else:
        for line in (9.5, 10.5, 11.5):
            p = poisson_over(cor_h + cor_a, line)
            if p >= settings.min_prob:
                emit(tracked, "corners", f"Córners partido +{line}", line, p, None, None, 2)
    for line in (3.5, 4.5, 5.5):
        p = poisson_over(cor_h, line)
        if p >= settings.min_prob:
            emit(tracked, "corners", f"{home_name} córners +{line}", line, p, None, None, 2)
        p = poisson_over(cor_a, line)
        if p >= settings.min_prob:
            emit(tracked, "corners", f"{away_name} córners +{line}", line, p, None, None, 2)

    # 3) BTTS
    p_b = p_btts(matrix)
    by, bn = odds.btts.get("yes"), odds.btts.get("no")
    imp_y = devig_prob(by, bn, "over")
    imp_n = devig_prob(by, bn, "under")
    if by and imp_y is not None and (p_b - imp_y) >= settings.min_edge and p_b >= settings.min_prob:
        emit(value, "btts", "Ambos anotan: Sí", None, p_b, by, imp_y, 3)
    p_bn = 1 - p_b
    if bn and imp_n is not None and (p_bn - imp_n) >= settings.min_edge and p_bn >= settings.min_prob:
        emit(value, "btts", "Ambos anotan: No", None, p_bn, bn, imp_n, 3)

    # 4) MÁS/MENOS GOLES (líneas disponibles en cuotas)
    for line, sides in odds.total_goals.items():
        try:
            L = float(line)
        except ValueError:
            continue
        po_, pu_ = sides.get("over"), sides.get("under")
        imp_o = devig_prob(po_, pu_, "over")
        imp_u = devig_prob(po_, pu_, "under")
        p_o = p_over(matrix, L)
        if po_ and imp_o is not None and (p_o - imp_o) >= settings.min_edge and p_o >= settings.min_prob:
            emit(value, "totals", f"Goles partido +{L}", L, p_o, po_, imp_o, 4)
        p_u = 1 - p_o
        if pu_ and imp_u is not None and (p_u - imp_u) >= settings.min_edge and p_u >= settings.min_prob:
            emit(value, "totals", f"Goles partido -{L}", L, p_u, pu_, imp_u, 4)

    # 5) GOLES POR EQUIPO (team totals)
    for line, teams in (odds.team_totals or {}).items():
        try:
            L = float(line)
        except ValueError:
            continue
        for tn, sides in teams.items():
            if tn == hn:
                lam_t, label = lam_h, home_name
            elif tn == an:
                lam_t, label = lam_a, away_name
            else:
                continue
            po_, pu_ = sides.get("over"), sides.get("under")
            imp_o = devig_prob(po_, pu_, "over")
            imp_u = devig_prob(po_, pu_, "under")
            p_o = poisson_over(lam_t, L)
            if po_ and imp_o is not None and (p_o - imp_o) >= settings.min_edge and p_o >= settings.min_prob:
                emit(value, "team_totals", f"{label} goles +{L}", L, p_o, po_, imp_o, 5)
            p_u = 1 - p_o
            if pu_ and imp_u is not None and (p_u - imp_u) >= settings.min_edge and p_u >= settings.min_prob:
                emit(value, "team_totals", f"{label} goles -{L}", L, p_u, pu_, imp_u, 5)

    # 6) 1X2 (prioridad más baja; el mercado suele estar muy eficiente)
    probs = {"home": p_home_win(matrix), "draw": p_draw(matrix), "away": p_away_win(matrix)}
    prices = {s: odds.match_odds.get(s) for s in probs}
    if all(prices.values()):
        inv = {s: 1.0 / prices[s] for s in prices}
        z = sum(inv.values())
        labels = {"home": home_name, "draw": "Empate", "away": away_name}
        for s in probs:
            implied = inv[s] / z
            if (probs[s] - implied) >= settings.min_edge and probs[s] >= settings.min_prob:
                emit(value, "match_odds", f"1X2: {labels[s]}", None, probs[s], prices[s], implied, 6)

    return value, tracked


# ---------------------------------------------------------------- selección final
def rank_value(cands: list[Candidate], settings: Settings) -> list[Candidate]:
    """Picks de valor: filtro de edge/probabilidad, orden por prioridad y confianza."""
    eligible = [c for c in cands if c.has_odds and c.edge is not None
                and c.edge >= settings.min_edge and c.model_prob >= settings.min_prob
                and c.stake_pct > 0]
    eligible.sort(key=lambda c: (PRIORITY.get(c.market, 9), -c.confidence))
    return eligible[: settings.max_picks]


def top_tracked(cands: list[Candidate], limit: int = 8) -> list[Candidate]:
    """Seguimiento del modelo (sin cuota disponible): los más probables por prioridad."""
    pool = [c for c in cands if not c.has_odds and c.model_prob >= 0.60]
    pool.sort(key=lambda c: (PRIORITY.get(c.market, 9), -c.model_prob))
    return pool[:limit]
