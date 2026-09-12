"""Punto de entrada: orquesta APIs -> modelo -> valor -> reporte.

Uso local:  python -m src.main
Uso CI:     python -m src.main   (variables por entorno)
"""
from __future__ import annotations

from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # en CI no hace falta
    pass

from .clients.odds_api import TheOddsAPI
from .clients.stats_api import StatsAPIError, TheStatsAPI
from .config import Settings
from .engine import (
    build_candidates,
    goal_lambdas,
    merge_odds,
    norm,
    normalize_odds_event,
    parse_stats_odds,
    rank_value,
    top_tracked,
)
from .models import MatchOdds, TeamSeasonStats
from .report import write_reports


def fetch_odds_index(api: TheOddsAPI, settings: Settings) -> dict[tuple[str, str], dict]:
    """Índice de eventos TheOddsAPI por par de equipos normalizado."""
    index: dict[tuple[str, str], dict] = {}
    for sport_key in settings.odds_sport_keys:
        for ev in api.odds(sport_key):
            key = (norm(ev.get("home_team", "")), norm(ev.get("away_team", "")))
            index[key] = ev
    return index


def process_fixture(fx, stats: TheStatsAPI, odds_index: dict, settings: Settings):
    """Procesa un partido: stats -> lambdas -> mercados -> candidatos."""
    season_id = fx.season_id or stats.current_season(fx.competition_id)
    if season_id:
        home_season = stats.team_season_stats(fx.home_id, season_id)
        away_season = stats.team_season_stats(fx.away_id, season_id)
    else:
        home_season = TeamSeasonStats(team_id=fx.home_id)
        away_season = TeamSeasonStats(team_id=fx.away_id)

    rh = stats.recent_stats(fx.home_id, fx.competition_id, settings.sot_lookback)
    ra = stats.recent_stats(fx.away_id, fx.competition_id, settings.sot_lookback)

    lam_h, lam_a = goal_lambdas(home_season, away_season, rh, ra,
                                settings.form_weight, settings.home_boost)

    hn, an = norm(fx.home_name), norm(fx.away_name)
    odds = MatchOdds()
    ev = odds_index.get((hn, an))
    if ev:
        odds = normalize_odds_event(ev, fx.home_name, fx.away_name)
    odds = merge_odds(odds, parse_stats_odds(stats.match_odds(fx.match_id)))

    value, tracked = build_candidates(fx.home_name, fx.away_name, hn, an,
                                      odds, lam_h, lam_a, rh, ra, settings)
    kick = fx.utc_date[:16].replace("T", " ")
    for c in value + tracked:
        c.match = f"{fx.home_name} vs {fx.away_name}"
        c.kickoff = kick
    return value, tracked, (lam_h, lam_a)


def main() -> int:
    settings = Settings.from_env()
    settings.validate()
    target = settings.fixture_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    stats = TheStatsAPI(settings)
    odds_api = TheOddsAPI(settings)
    odds_index = fetch_odds_index(odds_api, settings)

    diagnostics = [
        f"Fecha objetivo (UTC): {target}",
        f"Competiciones: {', '.join(settings.competition_ids)}",
        f"Eventos TheOddsAPI indexados: {len(odds_index)}",
    ]

    all_value, all_tracked = [], []
    processed = 0
    for comp_id in settings.competition_ids:
        try:
            fixtures = stats.fixtures(comp_id, target)
        except StatsAPIError as exc:
            diagnostics.append(f"{comp_id}: error listando fixtures: {exc}")
            continue
        diagnostics.append(f"{comp_id}: {len(fixtures)} partidos programados")
        for fx in fixtures:
            try:
                value, tracked, _ = process_fixture(fx, stats, odds_index, settings)
                all_value.extend(value)
                all_tracked.extend(tracked)
                processed += 1
            except Exception as exc:  # un partido malo no tumba la corrida
                diagnostics.append(f"{fx.match_id} {fx.home_name} vs {fx.away_name}: "
                                   f"{exc.__class__.__name__}: {exc}")

    picks = rank_value(all_value, settings)
    tracked_sel = top_tracked(all_tracked, limit=8)
    diagnostics.append(f"Partidos procesados: {processed}")
    diagnostics.append(f"Picks de valor: {len(picks)} | Seguimiento: {len(tracked_sel)}")
    diagnostics.append(f"Créditos TheOddsAPI restantes: {odds_api.credits_remaining}")

    md_path, json_path = write_reports(target, picks, tracked_sel, diagnostics, settings.output_dir)

    print(f"[OK] Reportes: {md_path} | {json_path}")
    for d in diagnostics:
        print(f"  - {d}")
    if picks:
        best = picks[0]
        print(f"[PICK TOP] {best.selection} | {best.match} | prob {best.model_prob:.2%} "
              f"| cuota {best.odds} | edge {best.edge:.2%} | stake {best.stake_pct}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
