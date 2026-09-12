"""Cliente TheOddsAPI v4 — https://api.the-odds-api.com/v4 (auth: apiKey query param).

Docs: https://the-odds-api.com/liveapi/guides/v4/
Cada respuesta expone headers de cuota: x-requests-remaining / x-requests-used.
"""
from __future__ import annotations

import time

import requests

from ..config import Settings


class OddsAPIError(Exception):
    pass


class TheOddsAPI:
    BASE = "https://api.the-odds-api.com/v4"

    def __init__(self, settings: Settings):
        self.s = settings
        self.session = requests.Session()
        self.credits_remaining: int | None = None
        self.credits_used: int | None = None

    def _get(self, path: str, retries: int | None = None, **params) -> dict | list:
        params["apiKey"] = self.s.odds_api_key
        url = self.BASE + path
        retries = retries if retries is not None else self.s.retries
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.s.timeout)
                if "x-requests-remaining" in r.headers:
                    self.credits_remaining = int(r.headers["x-requests-remaining"])
                if "x-requests-used" in r.headers:
                    self.credits_used = int(r.headers["x-requests-used"])
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 ** attempt)
        raise OddsAPIError(f"GET {url} falló tras {retries} intentos: {last_exc}")

    def odds(self, sport_key: str, markets: str = "h2h,totals,btts,team_totals") -> list[dict]:
        """Eventos con cuotas. Devuelve [] si no hay key o falla (el modelo sigue con TheStatsAPI)."""
        if not self.s.odds_api_key:
            return []
        try:
            return self._get(
                f"/sports/{sport_key}/odds",
                regions=self.s.regions,
                markets=markets,
                oddsFormat="decimal",
            )
        except OddsAPIError:
            return []
