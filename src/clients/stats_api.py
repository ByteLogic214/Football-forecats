"""Cliente TheStatsAPI — https://api.thestatsapi.com/api (auth: Bearer token).

Docs oficiales (AI-readable): https://api.thestatsapi.com/llms.txt
"""
from __future__ import annotations

import time

import requests

from ..config import Settings
from ..models import Fixture, TeamRecentStats, TeamSeasonStats


class StatsAPIError(Exception):
    pass


class TheStatsAPI:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.stats_api_key}",
            "Accept": "application/json",
        })

    def _get(self, path: str, retries: int | None = None, **params) -> dict:
        url = f"{self.s.stats_base_url.rstrip('/')}{path}"
        params = {k: v for k, v in params.items() if v is not None}
        retries = retries if retries is not None else self.s.retries
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.s.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise StatsAPIError(f"GET {url} falló tras {retries} intentos: {last_exc}")

    # ---------- catálogo ----------
    def competitions(self, search: str | None = None) -> list[dict]:
        return self._get("/football/competitions", per_page=100, search=search).get("data", [])

    def current_season(self, competition_id: str) -> str | None:
        d = self._get(f"/football/competitions/{competition_id}").get("data", {})
        return d.get("current_season_id")

    # ---------- partidos ----------
    def fixtures(self, competition_id: str, date: str) -> list[Fixture]:
        """Partidos programados de una competencia para una fecha (UTC)."""
        out: list[Fixture] = []
        page = 1
        while True:
            d = self._get(
                "/football/matches",
                competition_id=competition_id,
                date_from=date,
                date_to=date,
                status="scheduled",
                per_page=100,
                page=page,
            )
            for m in d.get("data", []):
                out.append(Fixture(
                    match_id=m["id"],
                    competition_id=m["competition_id"],
                    season_id=m.get("season_id", "") or "",
                    utc_date=m["utc_date"],
                    home_id=m["home_team"]["id"],
                    home_name=m["home_team"]["name"],
                    away_id=m["away_team"]["id"],
                    away_name=m["away_team"]["name"],
                ))
            meta = d.get("meta", {})
            if page >= meta.get("total_pages", 1):
                return out
            page += 1

    def team_season_stats(self, team_id: str, season_id: str) -> TeamSeasonStats:
        d = self._get(f"/football/teams/{team_id}/stats", season_id=season_id).get("data", {})
        return TeamSeasonStats(
            team_id=team_id,
            played=d.get("matches_played", 0) or 0,
            goals_for=d.get("goals_for", 0) or 0,
            goals_against=d.get("goals_against", 0) or 0,
            form=d.get("form", "") or "",
        )

    def match_stats(self, match_id: str) -> dict:
        return self._get(f"/football/matches/{match_id}/stats").get("data", {})

    def match_odds(self, match_id: str) -> dict:
        """Cuotas TheStatsAPI del partido: match_odds, btts, total_goals, match_corners, asian_handicap."""
        try:
            return self._get(f"/football/matches/{match_id}/odds").get("data", {})
        except StatsAPIError:
            return {}

    def recent_stats(self, team_id: str, competition_id: str, lookback: int) -> TeamRecentStats:
        """Medias reales de los últimos `lookback` partidos terminados del equipo:
        goles, remates totales, remates al arco y córners (a favor y en contra)."""
        d = self._get(
            "/football/matches",
            team_id=team_id,
            competition_id=competition_id,
            status="finished",
            per_page=lookback,
        )
        rows = d.get("data", [])[:lookback]
        acc = dict(n=0, gf=0, ga=0, sf=0, sa=0, sotf=0, sota=0, cf=0, ca=0)

        def val(section: dict, key: str, side: str) -> float:
            node = (section or {}).get(key) or {}
            return ((node.get("all") or {}).get(side)) or 0

        for m in rows:
            stats = self.match_stats(m["id"])
            shots = stats.get("shots", {})
            overview = stats.get("overview", {})
            is_home = m["home_team"]["id"] == team_id
            side = "home" if is_home else "away"
            opp = "away" if is_home else "home"
            sc = m.get("score") or {}
            acc["n"] += 1
            acc["gf"] += (sc.get(side) or 0)
            acc["ga"] += (sc.get(opp) or 0)
            acc["sf"] += val(shots, "total_shots", side)
            acc["sa"] += val(shots, "total_shots", opp)
            acc["sotf"] += val(shots, "shots_on_target", side)
            acc["sota"] += val(shots, "shots_on_target", opp)
            acc["cf"] += val(overview, "corner_kicks", side)
            acc["ca"] += val(overview, "corner_kicks", opp)

        n = acc["n"]
        if n == 0:
            return TeamRecentStats(matches_used=0)  # el modelo usará sus defaults
        return TeamRecentStats(
            matches_used=n,
            goals_for_pg=acc["gf"] / n,
            goals_against_pg=acc["ga"] / n,
            shots_for_pg=acc["sf"] / n or 12.0,
            shots_against_pg=acc["sa"] / n or 12.0,
            sot_for_pg=acc["sotf"] / n or 4.2,
            sot_against_pg=acc["sota"] / n or 4.2,
            corners_for_pg=acc["cf"] / n or 5.0,
            corners_against_pg=acc["ca"] / n or 5.0,
        )
